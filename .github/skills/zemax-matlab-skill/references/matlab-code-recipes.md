# MATLAB 代码模板（Zemax 辅助）

> 全部代码为**基础 MATLAB**，不依赖工具箱（除已注明处）。注释中文，R2020a+ 默认 UTF-8 可直接用。
> 落地方式：写成 `<项目目录>/<任务>_<日期>.m`（如 `zemax-ADAS/stopfix_v8/`），
> 再用 `mcp__matlab__run_matlab_file` 跑；不要在 `evaluate_matlab_code` 里塞长代码。
> 下文相对路径均指**项目目录**，脚本一律自定位：`base = fileparts(mfilename('fullpath'));`

## 0. 开工三件事

```matlab
% 1) 确认环境（对应 MCP 工具 detect_matlab_toolboxes）
disp(version)
disp(matlabroot)

% 2) 建目录（幂等；base = 脚本所在项目目录）
base = fileparts(mfilename('fullpath'));
if isempty(base); base = pwd; end
for d = {fullfile(base,'data'), fullfile(base,'figs'), fullfile(base,'analysis')}
    if ~isfolder(d{1}), mkdir(d{1}); end
end

% 3) 固定随机数，保证结果可复现
rng(0);
```

## 1. 偶次非球面：矢高、斜率、二阶导

```matlab
function [z, dz, d2z] = asphere_sag(r, R, k, A)
%ASPHERE_SAG  偶次非球面矢高及一、二阶导
%   r : 径向坐标 (mm)，可为向量
%   R : 顶点曲率半径 (mm)；k : 圆锥系数
%   A : [A4 A6 A8 ...]，与 r^4, r^6, ... 对应；可为空
%   z = c*r^2/(1+sqrt(1-(1+k)c^2r^2)) + sum(A_n * r^(2n+2))
c  = 1/R;
rr = r(:).';
s  = 1 - (1+k)*c^2*rr.^2;              % 根号内
if any(s <= 0)
    error('asphere_sag: r 超出圆锥面有效范围（根号内 <= 0）');
end
z   = c*rr.^2 ./ (1 + sqrt(s));
dz  = c*rr ./ sqrt(s);
d2z = c ./ s.^(3/2);                   % 圆锥面二阶导，闭式解
A = A(:).';
for n = 1:numel(A)
    m   = 2*n + 2;
    z   = z   + A(n)*rr.^m;
    dz  = dz  + m*A(n)*rr.^(m-1);
    d2z = d2z + m*(m-1)*A(n)*rr.^(m-2);
end
end
```

调用与输出表：

```matlab
R = -62.6; k = -1.2; A = [1.2e-5 3.4e-8];
r = linspace(0, 8, 2001);              % 8 mm 通光半径
[z, dz, d2z] = asphere_sag(r, R, k, A);

T = table(r.', z.', dz.', d2z.', ...
    'VariableNames', {'r_mm','sag_mm','slope','curvature'});
writetable(T, 'data/sag.csv');
```

## 2. 反曲点（斜率变号）与拐点（二阶导变号）

```matlab
function [r_rev, r_infl] = find_reverse_curvature(R, k, A, r_max)
%FIND_REVERSE_CURVATURE  口径内第一个斜率变号 / 二阶导变号位置
%   未出现返回 NaN
rr = linspace(0, r_max, 4001);
[~, dz, d2z] = asphere_sag(rr, R, k, A);

r_rev  = first_zero_cross(dz,  rr, R, k, A, 1);
r_infl = first_zero_cross(d2z, rr, R, k, A, 2);
end

function x0 = first_zero_cross(v, rr, R, k, A, order)
idx = find(v(1:end-1).*v(2:end) < 0, 1, 'first');
if isempty(idx)
    x0 = NaN; return
end
f  = @(x) nth_out(x, R, k, A, order);
x0 = fzero(f, [rr(idx) rr(idx+1)]);
end

function v = nth_out(x, R, k, A, order)
[~, dz, d2z] = asphere_sag(x, R, k, A);
if order == 1
    v = dz;
else
    v = d2z;
end
end
```

判据（来自 `zemax-asphere-skill`）：

- `r_rev` 有限 → **斜率变号 = 反曲，不合格**；
- 余量 = `(r_max - r_rev)/r_max`，**<5% 按不合格**；
- `r_infl` 有限 → 报告位置并评估抛光风险。

## 3. 最佳拟合球 BFS 与非球面度

```matlab
function [Rbfs, dev, bfs_pv] = bfs_vertex(r, z, R0)
%BFS_VERTEX  过顶点的最佳拟合球：z_s(r) = R - sqrt(R^2 - r^2)
%   R0 : 初值，必须 > max(r)（一般取值域半径的 3~10 倍）
r = r(:); z = z(:); rmax = max(r);
cost = @(R) bfs_cost(R, r, z, rmax);
opts = optimset('TolX', 1e-10, 'Display', 'off');
Rbfs = fminsearch(cost, R0, opts);
dev  = z - (Rbfs - sqrt(Rbfs^2 - r.^2));
bfs_pv = max(dev) - min(dev);          % 非球面度（峰谷）
end

function v = bfs_cost(R, r, z, rmax)
if R <= rmax*1.05
    v = 1e6 + (rmax*1.05 - R);         % 罚函数：球面必须覆盖口径
    return
end
v = max(abs(z - (R - sqrt(R.^2 - r.^2))));   % 最小最大偏离
end
```

```matlab
[Rbfs, dev, pv] = bfs_vertex(r, z, 200);
fprintf('BFS R = %.3f mm, 非球面度 PV = %.3f um\n', Rbfs, pv*1000);
```

> 与 OpticStudio 的 Sag 表读数对一下量级；数量级不一致先查符号约定与口径。

## 4. 公差蒙特卡洛统计（良率 / CPK / 置信区间）

输入：单列 CSV，每次 trial 一个判据值（例如 RMS 光斑半径，单位 µm）。

```matlab
function s = mc_stats(x, spec, is_upper)
%MC_STATS  单侧/双侧规格的良率统计（不依赖 Statistics Toolbox）
if nargin < 3, is_upper = true; end
x = x(:); x = x(isfinite(x));
N = numel(x);
if is_upper
    ok = x <= spec;
    s.cpk = (spec - mean(x))/(3*std(x));
    s.worst = max(x);
else
    ok = x >= spec;
    s.cpk = (mean(x) - spec)/(3*std(x));
    s.worst = min(x);
end
s.N = N; s.yield = mean(ok); s.mu = mean(x); s.sigma = std(x);
if s.sigma == 0, s.cpk = Inf; end
s.p95 = local_pct(x, 95); s.p99 = local_pct(x, 99);

B = 5000; yb = zeros(B,1);
for b = 1:B
    idx = randi(N, N, 1);
    yb(b) = mean(ok(idx));
end
s.yield_ci = [local_pct(yb, 2.5) local_pct(yb, 97.5)];
end

function q = local_pct(x, p)
% 线性插值分位数，替代 prctile
xs = sort(x(:)); n = numel(xs);
if n == 0, q = NaN; return; end
pos = (p/100)*(n-1) + 1;
lo = floor(pos); hi = ceil(pos);
q = xs(lo) + (pos-lo)*(xs(hi)-xs(lo));
end
```

```matlab
x = readmatrix('data/tol_mc.csv');
s = mc_stats(x, 5.0, true);            % 规格：RMS <= 5.0 um
fprintf('N=%d  yield=%.1f%%  (95%% CI %.1f-%.1f%%)\n', ...
    s.N, 100*s.yield, 100*s.yield_ci);
fprintf('mu=%.3f  sigma=%.3f  P95=%.3f  P99=%.3f  CPK=%.2f  worst=%.3f\n', ...
    s.mu, s.sigma, s.p95, s.p99, s.cpk, s.worst);

histogram(x, 30, 'FaceColor', [0.30 0.45 0.70], 'EdgeColor', 'w');
xline(spec, 'r--', 'LineWidth', 1.2);
xlabel('RMS spot radius (\mum)'); ylabel('Count');
title(sprintf('Monte Carlo, N=%d, yield=%.1f%%', s.N, 100*s.yield));
exportgraphics(gcf, 'figs/tol_mc_hist.png', 'Resolution', 300);
close all;
```

**报告纪律**：良率必须带 N 和置信区间；只说"良率 92%"而不说 N=200、CI 88–95% 是不合格的。

## 5. 热离焦拟合与补偿行程

输入 CSV：`[T_C, bfl_drift_um]`。

```matlab
D = readmatrix('data/thermal.csv');
T = D(:,1); y = D(:,2);

p  = polyfit(T, y, 2);
resid = y - polyval(p, T);
span  = max(y) - min(y);

fprintf('温度跨度 %.0f ~ %.0f C\n', min(T), max(T));
fprintf('BFL 漂移峰峰值 = %.1f um\n', span);
fprintf('拟合残差最大值 = %.2f um\n', max(abs(resid)));
fprintf('建议补偿行程 = %.1f um（含 20%% 余量）\n', 1.2*span);

Tf = linspace(min(T), max(T), 200);
plot(T, y, 'o', Tf, polyval(p, Tf), '-', 'LineWidth', 1.2);
xlabel('Temperature (\circC)'); ylabel('BFL drift (\mum)');
legend('MCE data', 'quadratic fit', 'Location', 'best'); grid on;
exportgraphics(gcf, 'figs/thermal_defocus.png', 'Resolution', 300);
close all;
```

判据：残差 < 1/4 焦深（`焦深 ≈ 2*lambda*F#^2`）。最终以 Zemax 全温 MTF 为准。

## 6. MTF / 相对照度 / 畸变出图

CSV 约定：第 1 列自变量，其后每个视场一列。

```matlab
M = readmatrix('data/mtf.csv');
f = M(:,1); mtf = M(:,2:end);

plot(f, mtf, 'LineWidth', 1.2);
xlabel('Spatial frequency (lp/mm)'); ylabel('MTF');
xlim([0 120]); ylim([0 1]); grid on;
legend(compose('Field %d', 1:size(mtf,2)), 'Location', 'northeast');
set(findall(gcf,'-property','FontName'), 'FontName', 'Microsoft YaHei');
set(gca, 'FontSize', 9, 'LineWidth', 0.8, 'GridAlpha', 0.15);
exportgraphics(gcf, 'figs/mtf.png', 'Resolution', 300);
close all;
```

多条曲线超过 6 条时，按视场分组 + 线型（实线/虚线）区分，或拆成 2×3 `tiledlayout`。

## 7. 把 Zemax 工具返回的 JSON 变成 CSV（Python 侧）

MATLAB 不直接读 MCP 的返回值。让 agent 先把 JSON 落盘，再用 6 行 Python 转 CSV：

```python
# scripts/zemax_json_to_csv.py  —— 用法: python ... raw.json out.csv key1,key2
import json, sys, csv
raw = json.load(open(sys.argv[1], encoding="utf-8"))
rows = raw["fields"]                       # 键名以实际返回为准，先打印结构再写
keys = sys.argv[3].split(",")
with open(sys.argv[2], "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f); w.writerow(keys)
    for r in rows:
        w.writerow([r.get(k, "") for k in keys])
```

**先 `print(list(raw.keys()))` 看结构**，不要凭记忆猜字段名——不同工具、不同版本返回的键不一样。

## 8. 收尾模板

```matlab
close all;
fprintf('DONE: 图在 figs/，数据在 data/\n');
```

一次 MATLAB 调用里把读数据、算、出图、关图全部做完；不要把同一个任务拆成五六次 `evaluate_matlab_code`，既慢又容易在会话里丢状态。
