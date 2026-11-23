%% Zemax 鬼像焦点生成器 ↔ 一阶 y–nu 模型 交叉验证
% 输入：zemax-ADAS/no_ir_cut/data/ghost_zemax_20261119.csv  （GUI 输出转录，55 组）
%       zemax-ADAS/no_ir_cut/data/ghost_pairs_final.csv      （一阶模型，66 组，含像面反射）
% 输出：no_ir_cut/figs/ghost_zemax_vs_firstorder.png
clear; clc; close all;

rootDir = 'D:\Zemax-mcp';
Z = readtable(fullfile(rootDir,'zemax-ADAS','no_ir_cut','data','ghost_zemax_20261119.csv'));
F = readtable(fullfile(rootDir,'zemax-ADAS','no_ir_cut','data','ghost_pairs_final.csv'));
outPng = fullfile(rootDir,'zemax-ADAS','no_ir_cut','figs','ghost_zemax_vs_firstorder.png');

IMG_SD = 4.6563;         % 像面半口径（仅作参考，不用于判落点）
% 注意：Zemax「到鬼像焦点的距离」以像面为原点（2026-11-19 核对：12-13 组差 0.6 µm），
% 不要再减 BFL —— 旧版多减 0.9 mm，已更正。

% ---- 按 (j,i) 配对 ----
n = height(Z);
mz = zeros(n,1);
for k = 1:n
    idx = find(F.surface_i == Z.i_surface(k) & F.surface_j == Z.j_surface(k), 1);
    if ~isempty(idx), mz(k) = idx; else, mz(k) = NaN; end
end
match = ~isnan(mz) & Z.rms_mm > 0;          % 只比较有效追迹
fprintf('Zemax %d 组，匹配到一阶模型 %d 组，有效(剔除 RMS=0) %d 组\n', ...
    n, sum(~isnan(mz)), sum(match));

zf = Z.d_focus_mm(match);
z1 = F.z_ghost_mm(mz(match));
dz = zf - z1;

% ---- 相关性 ----
R1 = corrcoef(zf, z1); r1 = R1(1,2);
rms = Z.rms_mm(match);
D1  = F.blur_D_mm(mz(match));
R2 = corrcoef(rms, D1); r2 = R2(1,2);

fprintf('\n[1] 鬼像焦点位置  Zemax d_focus ↔ 一阶 z_ghost\n');
fprintf('    corr = %+.4f   最大偏差 = %.4f mm   RMS 偏差 = %.4f mm\n', r1, max(abs(dz)), sqrt(mean(dz.^2)));
fprintf('[2] 弥散斑  Zemax RMS ↔ 一阶 D\n');
fprintf('    corr = %+.4f（两者物理量不同，仅趋势可比）\n', r2);
fprintf('    RMS/D 中位数 = %.3f，四分位区间 [%.3f, %.3f]\n', ...
    median(rms./D1), prctile(rms./D1,25), prctile(rms./D1,75));
% 离群：一阶 D 明显低估（早期面组合大角度偏离近轴）
ratio = rms./D1;
[~,ro] = sort(abs(log(ratio)),'descend');
Zm0 = find(match);
fprintf('    最偏离的组合：');
for q = 1:3
    r0 = Zm0(ro(q));
    fprintf('%d-%d(RMS/D=%.2f) ', Z.j_surface(r0), Z.i_surface(r0), ratio(ro(q)));
end
fprintf('\n');
keep = true(size(ratio)); keep(ro(1:3)) = false;
R3 = corrcoef(rms(keep), D1(keep));
fprintf('    剔除这 3 个离群后 corr = %+.4f\n', R3(1,2));

% ---- 离像面距离（d_focus 已以像面为原点） ----
dist = abs(Z.d_focus_mm);
valid = Z.rms_mm > 0;
score = dist; score(~valid) = Inf;
[~, ord] = sort(score);
fprintf('\n%-12s %10s %10s %9s %9s  %s\n', '面组合','d_focus','离像面','RMS','光瞳距','判定');
for r = 1:min(12, n)
    k = ord(r);
    if ~isfinite(score(k)), break; end
    nm = sprintf('%d-%d', Z.j_surface(k), Z.i_surface(k));
    v = '锐利·重点';
    if Z.rms_mm(k) > 0.5, v = '偏锐利'; end
    if Z.rms_mm(k) > 1.0, v = '弥散'; end
    fprintf('%-12s %10.3f %10.3f %9.4f %9.3f  %s\n', nm, Z.d_focus_mm(k), ...
        Z.d_focus_mm(k), Z.rms_mm(k), Z.d_pupil_mm(k), v);
end

zeroRms = sum(Z.rms_mm == 0);
fprintf('\n有效组合 %d 个（剔除 RMS=0 失败行 %d 个）\n', sum(valid), zeroRms);
fprintf('「主光线高度」不是像面落点：轴向场下旋转对称 ⇒ 落点必在轴上（实光线模型 66 组全部 0.000 mm），\n');
fprintf('  Zemax 该列与自身 edge/RMS 列矛盾（13-12: chief 5.57 vs edge −0.64），不要用它判落点。\n');

% 最近瞳孔鬼影（不形成亮点，但降低全画面对比度）
[~, pk] = sort(abs(Z.d_pupil_mm));
fprintf('\n最近鬼像光瞳：%d-%d  %.4f mm；%d-%d  %.4f mm\n', ...
    Z.j_surface(pk(1)), Z.i_surface(pk(1)), Z.d_pupil_mm(pk(1)), ...
    Z.j_surface(pk(2)), Z.i_surface(pk(2)), Z.d_pupil_mm(pk(2)));

% ---- 图 ----
fig = figure('Visible','off','Color','w','Position',[80 80 1360 560]);
tl = tiledlayout(fig,1,2,'Padding','compact','TileSpacing','compact');

ax1 = nexttile(tl); hold(ax1,'on');
scatter(ax1, z1, zf, 40, dist(match), 'filled', 'MarkerEdgeColor','none');
lim = [min([z1;zf])-2, max([z1;zf])+2];
plot(ax1, lim, lim, 'k--', 'LineWidth', 1.0);
xlim(ax1, lim); ylim(ax1, lim);
cb = colorbar(ax1); cb.Label.String = '|离像面| (mm)';
xlabel(ax1,'一阶模型 z_{ghost} (mm)');
ylabel(ax1,'Zemax 到鬼像焦点的距离 (mm)');
title(ax1, sprintf('鬼像焦点位置  corr = %+.4f', r1));
grid(ax1,'on'); box(ax1,'off'); axis(ax1,'square');

% 右图：离像面距离 × 弥散 —— 直接可判的危险度平面
dv = dist(match);
ax2 = nexttile(tl); hold(ax2,'on');
scatter(ax2, dv, rms, 40, [0.85 0.33 0.10], 'filled', 'MarkerEdgeColor','none');
set(ax2,'XScale','log','YScale','log');
xlim(ax2,[0.04 max(dv)*1.4]); ylim(ax2,[0.2 4]);
% 危险区：离像面 <0.5 mm 且 RMS <0.3 mm（锐利且落在传感器上）
patch(ax2,[0.04 0.5 0.5 0.04],[0.2 0.2 0.3 0.3],[1 0.85 0.85], ...
    'EdgeColor','none','FaceAlpha',0.55);
text(ax2,0.07,0.235,'危险区','FontSize',8,'Color',[0.6 0.1 0.1]);
% 标注离像面最近的三个（k 是子集下标，需映射回 Z 的行号）
Zm = find(match);
[~,so] = sort(dv);
dy = [1.28 1.16 1.28];
for q = 1:3
    k = so(q);
    r0 = Zm(k);
    text(ax2, dv(k)*1.10, rms(k)*dy(q), sprintf('%d-%d',Z.j_surface(r0),Z.i_surface(r0)), ...
        'FontSize',8,'Color',[0.4 0.15 0.05],'BackgroundColor','w','Margin',0.6);
end
xlabel(ax2,'|离像面距离| (mm)');
ylabel(ax2,'Zemax RMS 光斑半径 (mm)');
title(ax2,'危险度平面：左下 = 近焦且锐利（轴向落点均在像面中心）');
grid(ax2,'on'); box(ax2,'off');

title(tl,'Zemax 鬼像焦点生成器 ↔ 一阶 y–nu 模型 · 6 片 15 mm F/1.4', ...
    'FontSize',12,'FontWeight','bold');
set(findall(fig,'-property','FontName'),'FontName','Microsoft YaHei');
set(findall(fig,'-property','FontSize'),'FontSize',9);
exportgraphics(fig, outPng, 'Resolution', 300);
close(fig);
fprintf('\n图: %s\n', outPng);
