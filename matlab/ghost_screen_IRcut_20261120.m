%% 鬼影联合分析（2026-11-20）——一阶枚举 × Zemax GUI 真实光线
% 左：GUI「鬼像焦点生成器」导出（真实光线，含像面反射），文件：
%     zemax-ADAS/加窗口鬼影分析1-15.txt / 1-14.txt / 14-15.txt（UTF-16LE）
% 右：本引擎一阶 y-u 双次反射枚举（路线 B），同一套面表
% 输出：layouts/GHOST_IRcut.png（三联图）+ 控制台联合排序表
clear; clc; close all;

root = fileparts(fileparts(mfilename('fullpath')));
za   = fullfile(root, 'zemax-ADAS');
outd = fullfile(za, 'layouts');

%% ---------- 1. 面表（Zemax 公差Q5 副本；nd 取自 CDGM.AGF d 线）----------
% 列：R(mm)  t 到下一面(mm)  本面之后的折射率  半口径(mm)
S = [ ...
    34.78036051606992   3.307824716548504  1.581440   8.0
    17.435718549658848  4.0                1.0        8.0
    20.530294107490068  4.0797171225286855 1.772880   7.0
   -28.595593345652322  0.47               1.0        7.0
    Inf                 0.49               1.0        5.2600      % S5 光阑
    10.352808109044268  4.073732764136589  1.774000   5.5
   -38.17719639780744   2.039046734811184  1.805180   5.0
     5.624211470379923  3.8                1.0        3.8
    14.034021134058413  4.288669457140633  1.772880   5.5
   -12.052375463335132  1.0                1.0        5.5
    -6.407646360638522  1.3510440336689604 1.487490   5.0
    Inf                 0.7                1.0        5.0
    Inf                 0.4                1.516800   6.0        % IR-CUT + CG 板前
    Inf                 0.0                1.0        6.0        % 板后（与像面重合）
    Inf                 0.0                1.0        4.6504 ];  % S15 像面

R  = S(:,1);  tt = S(:,2);  nA = S(:,3);  SD = S(:,4);
N  = numel(R);
c  = zeros(N,1);  c(isfinite(R)) = 1 ./ R(isfinite(R));
nB = [1; nA(1:end-1)];

EFFL_zemax = 15.004572957873103;
TOTR_zemax = 30.000034828834558;

%% ---------- 2. 一阶校验 ----------
[~, uN]     = trace_ray(1.0, 0.0, 1, 14, c, tt, nA, nB);
EFFL_model  = -1.0 / uN;
TOTR        = sum(tt(1:14));
EPD         = EFFL_zemax / 1.4;
y1m         = EPD / 2;
[ym_img, ~] = trace_ray(y1m, 0.0, 1, 14, c, tt, nA, nB);

fprintf('=== 一阶校验（本引擎 vs Zemax）===\n');
fprintf('  EFFL  : %.4f  vs %.4f   (差 %+.4f mm)\n', EFFL_model, EFFL_zemax, EFFL_model - EFFL_zemax);
fprintf('  TOTR  : %.4f  vs %.4f   (差 %+.4f mm)\n', TOTR, TOTR_zemax, TOTR - TOTR_zemax);
fprintf('  像高(边缘光线) : %+.5f mm\n', ym_img);
assert(abs(EFFL_model - EFFL_zemax) < 0.02, 'EFFL 校验未通过');
assert(abs(TOTR - TOTR_zemax) < 1e-3,       'TOTR 校验未通过');
assert(abs(ym_img) < 0.01,                  '像高校验未通过');
fprintf('  → 通过\n\n');

%% ---------- 3. 读 Zemax GUI 导出 ----------
Z1  = read_ghost(fullfile(za, '加窗口鬼影分析1-15.txt'));
Z14 = read_ghost(fullfile(za, '加窗口鬼影分析1-14.txt'));
Z45 = read_ghost(fullfile(za, '加窗口鬼影分析14-15.txt'));
fprintf('=== Zemax GUI 导出 ===\n');
fprintf('  1-15 : %d 组   1-14 : %d 组   14-15 : %d 组\n', ...
    numel(Z1.pair), numel(Z14.pair), numel(Z45.pair));

% 三次运行的重叠面对必须逐位一致（同一系统、同一算法）
dmax = max_abs_diff(Z1, Z14);
dmax2 = max_abs_diff(Z1, Z45);
fprintf('  重叠面对「到鬼像焦点」最大偏差：1-14 对 1-15 = %.2e mm，14-15 对 1-15 = %.2e mm\n', dmax, dmax2);
nFail = sum(Z1.rms == 0);
fprintf('  RMS = 0.0000（追迹失败，非完美焦点）: %d / %d\n\n', nFail, numel(Z1.rms));

%% ---------- 4. 一阶枚举（含像面 S15，共 14 个反射面）----------
refl = [find(abs(nA - nB) > 1e-9); 15];
fprintf('反射面 %d 个 → 组合 C(%d,2) = %d（与 Zemax 的 91 组对齐）\n\n', ...
    numel(refl), numel(refl), numel(refl)*(numel(refl)-1)/2);

G = zeros(0, 6);   % [i j off D eta Irel]
for a = 1:numel(refl)
    for b = 1:a-1
        i = refl(a);  j = refl(b);
        g = ghost_pair(i, j, y1m, c, tt, nA, nB, SD);
        G(end+1, :) = [i, j, g.off, g.D, g.eta, g.Irel]; %#ok<SAGROW>
    end
end

%% ---------- 5. 联合：按面对合并 ----------
nZ = numel(Z1.pair);
row = zeros(nZ, 6);        % [off D eta Irel  ZemaxRMS  ZemaxFocus]
for k = 1:nZ
    p  = Z1.pair{k};
    q  = find(G(:,1) == p(1) & G(:,2) == p(2), 1);
    if isempty(q), continue; end
    row(k, :) = [G(q,3), G(q,4), G(q,5), G(q,6), Z1.rms(k), Z1.focus(k)];
end

% 交叉校验：一阶弥散 D  vs  Zemax 实光线 RMS（只比双方都有效的）
ok = row(:,5) > 0 & row(:,3) > 0.5 & row(:,2) > 0;
rr = corr(log(row(ok,2)), log(row(ok,5)));
fprintf('=== 交叉校验：一阶弥散 D vs Zemax RMS ===\n');
fprintf('  可比 %d 组，log-log 相关系数 r = %.3f\n', nnz(ok), rr);
fprintf('  （两条独立路线，只验证量级与排序是否同向，不追求逐位相等）\n\n');

%% ---------- 6. 联合排序表 ----------
[~, ordZ] = sort(row(:,5), 'descend');     % RMS 越大 = 鬼像越糊 = 越安全
ordZ = flipud(ordZ);
fprintf('=== 最尖锐的鬼像（Zemax 实光线 RMS 升序，剔除追迹失败）===\n');
fprintf('%4s %8s %10s %10s %10s %10s %9s\n', '#', '面对', 'ZemaxRMS', '像面边缘高', ...
    '鬼像焦点距', '一阶 Δz', '一阶浓度');
validAll = find(row(:,5) > 0);
[~, oo2] = sort(row(validAll,5), 'descend');
validAll = validAll(flipud(oo2));
shown = 0;
for k = 1:numel(validAll)
    q = validAll(k);
    shown = shown + 1;
    if shown > 12, break; end
    p = Z1.pair{q};
    fprintf('%4d %5d-%-3d %10.5f %10.5f %10.5f %10.4f %9.2e\n', shown, p(1), p(2), ...
        row(q,5), Z1.edge(q), row(q,6), row(q,1), row(q,4));
end

%% ---------- 7. 出图 ----------
fig = figure('Visible', 'off', 'Color', 'w', 'Position', [60 60 1860 520]);

% (a) 一阶弥散 D  vs  Zemax RMS
ax1 = subplot(1, 3, 1); hold(ax1, 'on');
x = row(ok,2);  y = row(ok,5);
scatter(ax1, x, y, 24, [0.32 0.52 0.78], 'filled', 'MarkerFaceAlpha', 0.8);
pf = polyfit(log(x), log(y), 1);
xx = linspace(min(x), max(x), 50);
plot(ax1, xx, exp(polyval(pf, log(xx))), 'k--', 'LineWidth', 1.0);
set(ax1, 'XScale', 'log', 'YScale', 'log');
xlim(ax1, [min(x)*0.7, max(x)*1.4]);
xlabel(ax1, '一阶弥散 D (mm，光瞳 6 点展宽)');
ylabel(ax1, 'Zemax 实光线 RMS 光斑半径 (mm)');
title(ax1, sprintf('弥散交叉校验　r = %.2f，斜率 %.2f（n=%d）', rr, pf(1), nnz(ok)), 'FontSize', 10);
grid(ax1, 'on'); box(ax1, 'off');

% (b) 最尖锐 Top-10
ax2 = subplot(1, 3, 2);
valid = find(row(:,5) > 0);
[~, oo] = sort(row(valid,5), 'descend');
valid = valid(flipud(oo));                 % 升序：最尖锐在前
nb = min(10, numel(valid));
lab = cell(nb, 1);  val = zeros(nb, 1);
for k = 1:nb
    q = valid(k);
    p = Z1.pair{q};
    lab{k} = sprintf('%d–%d', p(1), p(2));
    val(k) = row(q,5) * 1000;          % µm
end
b = barh(ax2, 1:nb, val, 0.62, 'EdgeColor', 'none');
b.FaceColor = 'flat';
cd = repmat([0.32 0.52 0.78], nb, 1);
cd(1, :) = [0.78 0.20 0.18];           % 最尖锐一条标红
b.CData = cd;
set(ax2, 'YDir', 'reverse', 'YTick', 1:nb, 'YTickLabel', lab, 'Box', 'off');
set(ax2, 'XScale', 'log');
xlabel(ax2, '鬼像在像面的 RMS 光斑半径 (µm，log)');
ylabel(ax2, '反射面对');
title(ax2, '最尖锐的 10 条（Zemax 实光线）', 'FontSize', 10);
grid(ax2, 'on');  xlim(ax2, [min(val)/2, max(val)*2]);

% (c) 鬼像焦点离像面的距离
ax3 = subplot(1, 3, 3); hold(ax3, 'on');
sel = row(:,5) > 0 & isfinite(row(:,6));
scatter(ax3, abs(row(sel,6)), row(sel,5), 24, [0.32 0.52 0.78], ...
    'filled', 'MarkerFaceAlpha', 0.8);
set(ax3, 'YScale', 'log');
xlabel(ax3, 'Zemax 鬼像焦点离像面的距离 |Δz| (mm)');
ylabel(ax3, 'Zemax RMS 光斑半径 (mm)');
title(ax3, '危险区：Δz→0 且 RMS 小（左上角）', 'FontSize', 10);
grid(ax3, 'on'); box(ax3, 'off');

sgtitle('鬼影联合分析　15mm F/1.4 六片定心版 + IR-CUT/CG 板　|　Zemax GUI 真实光线（91 组）× 一阶枚举', ...
    'FontSize', 12);
set(findall(fig, '-property', 'FontName'), 'FontName', 'Microsoft YaHei');
set(findall(fig, '-property', 'FontSize'), 'FontSize', 9);
p1 = fullfile(outd, 'GHOST_IRcut.png');
exportgraphics(fig, p1, 'Resolution', 300); close(fig);
fprintf('\n已输出 %s\n', p1);

%% ================= 局部函数 =================
function [y, u] = trace_ray(y, u, k1, kN, c, tt, nA, nB)
    for k = k1:kN
        u = (nB(k)*u - y*(nA(k) - nB(k))*c(k)) / nA(k);
        y = y + tt(k)*u;
    end
end

function g = ghost_pair(i, j, y1, c, tt, nA, nB, SD)
    N   = numel(c);
    py  = [0.10 0.30 0.50 0.70 0.90 1.00];
    ns  = numel(py);
    yj  = nan(ns,1);  uj = nan(ns,1);  yimg = nan(ns,1);  seen = false(ns,1);
    yd  = nan(ns,1);  ud = nan(ns,1);
    mTr = zeros(ns,1);

    for q = 1:ns
        [yj(q), uj(q), yimg(q), seen(q), mTr(q)] = ghost_trace(i, j, py(q)*y1, ...
            c, tt, nA, nB, SD);
        [yd(q), ud(q)] = direct_at(j, py(q)*y1, c, tt, nA, nB);
    end

    eta = mean(seen);
    ok  = seen;
    if nnz(ok) < 2
        g.dFocus = NaN;  g.dImg = NaN;  g.off = NaN;
        g.D = NaN;  g.eta = eta;  g.Irel = 0;  g.pass = false;
        return;
    end

    zstar   = best_focus(yj(ok), uj(ok));
    zdirect = best_focus(yd(ok), ud(ok));
    off     = zstar - zdirect;                     % 0 = 与主像焦点重合

    yo2 = yimg(ok);
    D = max(max(yo2) - min(yo2), 0.005);           % 下限 = 1 像元（5 µm）

    m   = max(mTr(ok));
    Ri  = 0.005;  if i == 15, Ri = 0.02; end       % 像面（CMOS 表面）反射率更高
    Rj  = 0.005;  if j == 15, Rj = 0.02; end
    Ii  = Ri * Rj * (1-0.005)^m * eta;

    g.dFocus = zstar;  g.dImg = sum(tt(j:N));  g.off = off;
    g.D = D;  g.eta = eta;  g.Irel = Ii / D^2;
    g.pass = eta > 0.5;
end

function [yj, uj, yimg, seen, nTr] = ghost_trace(i, j, y, c, tt, nA, nB, SD)
    N = numel(c);  seen = true;  nTr = 0;
    u = 0;
    for k = 1:i-1
        u = (nB(k)*u - y*(nA(k) - nB(k))*c(k)) / nA(k);
        y = y + tt(k)*u;
        if abs(y) > SD(k), seen = false; end
        nTr = nTr + 1;
    end

    u = -u - 2*c(i)*y;                             % 第一次反射
    if abs(y) > SD(i), seen = false; end

    for k = i-1:-1:j                               % 回程（展开：曲率取负、介质反向）
        y = y + tt(k)*u;
        if abs(y) > SD(k), seen = false; end
        if k == j, break; end
        u = (nA(k)*u - y*(nB(k) - nA(k))*(-c(k))) / nB(k);
        nTr = nTr + 1;
    end

    u = -u + 2*c(j)*y;                             % 第二次反射
    yj = y;  uj = u;

    for k = j+1:N
        y = y + tt(k-1)*u;
        if abs(y) > SD(k), seen = false; end
        u = (nB(k)*u - y*(nA(k) - nB(k))*c(k)) / nA(k);
        nTr = nTr + 1;
    end
    yimg = y + tt(N)*u;
end

function [y, u] = direct_at(j, y0, c, tt, nA, nB)
    y = y0;  u = 0;
    for k = 1:j-1
        u = (nB(k)*u - y*(nA(k) - nB(k))*c(k)) / nA(k);
        y = y + tt(k)*u;
    end
    u = (nB(j)*u - y*(nA(j) - nB(j))*c(j)) / nA(j);
end

function z = best_focus(y, u)
    if var(u) > 1e-16
        C = cov(y, u);                 % 2x2 协方差矩阵
        z = -C(1,2) / var(u);
    else
        z = 0;
    end
end

function Z = read_ghost(fn)
    fid = fopen(fn, 'rb');
    b = fread(fid, inf, 'uint8=>uint8');  fclose(fid);
    if numel(b) > 2 && b(1) == 255 && b(2) == 254, b = b(3:end); end
    u = uint16(b(1:2:end)) + 256 * uint16(b(2:2:end));
    L = strtrim(splitlines(string(char(u(:)'))));

    Z.pair = {};  Z.edge = [];  Z.rms = [];  Z.chf = [];
    Z.pupil = [];  Z.focus = [];  Z.efl = [];
    cur = [];
    for k = 1:numel(L)
        s = L(k);
        tk = regexp(s, '鬼像反射(\d+)然后(\d+)', 'tokens', 'once');
        if ~isempty(tk)
            cur = [str2double(tk{1}), str2double(tk{2})];
            continue;
        end
        if isempty(cur), continue; end
        f = regexp(s, '\S+', 'match');
        if numel(f) >= 4 && strcmp(f{1}, '15')
            num = str2double(f(2:4));
            if all(~isnan(num))
                Z.pair{end+1,1} = cur;
                Z.edge(end+1,1) = num(1);
                Z.rms(end+1,1)  = num(3);
            end
            continue;
        end
        v = regexp(s, '^主光线高度\s*:\s*(-?[\d.E+-]+)', 'tokens', 'once');
        if ~isempty(v), Z.chf(end+1,1) = str2double(v{1}); continue; end
        v = regexp(s, '^到鬼像光瞳的距离\s*:\s*(-?[\d.E+-]+)', 'tokens', 'once');
        if ~isempty(v), Z.pupil(end+1,1) = str2double(v{1}); continue; end
        v = regexp(s, '^到鬼像焦点的距离\s*:\s*(-?[\d.E+-]+)', 'tokens', 'once');
        if ~isempty(v), Z.focus(end+1,1) = str2double(v{1}); continue; end
        v = regexp(s, '^有效焦距\s*:\s*(-?[\d.E+-]+)', 'tokens', 'once');
        if ~isempty(v), Z.efl(end+1,1) = str2double(v{1}); end
    end
    n = numel(Z.pair);
    Z.edge = pad_to(Z.edge, n);  Z.rms = pad_to(Z.rms, n);
    Z.chf = pad_to(Z.chf, n);    Z.pupil = pad_to(Z.pupil, n);
    Z.focus = pad_to(Z.focus, n);  Z.efl = pad_to(Z.efl, n);
end

function v = pad_to(v, n)
    if numel(v) < n, v(end+1:n, 1) = NaN; end
end

function d = max_abs_diff(A, B)
    d = 0;  cnt = 0;
    for k = 1:numel(B.pair)
        q = find(cellfun(@(p) isequal(p, B.pair{k}), A.pair), 1);
        if isempty(q) || isnan(A.focus(q)) || isnan(B.focus(k)), continue; end
        d = max(d, abs(A.focus(q) - B.focus(k)));  cnt = cnt + 1;
    end
    if cnt == 0, d = NaN; end
end
