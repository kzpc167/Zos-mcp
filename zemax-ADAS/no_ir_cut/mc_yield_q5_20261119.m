%% Q5 公差蒙特卡洛良率分析（两批各 500 次，复色衍射 MTF@120 lp/mm）
% 数据来源（同一份 v2 公差表，不同随机种子）：
%   批 A：tol_q5_mc.txt 导出表（MC_n 行，第 2 列 = 衍射MTF平均）
%   批 B：tol_q5_总结.txt 报告内「蒙特卡罗分析」段（Zemax 自算的 500 次判据值）
%   → zemax-ADAS/no_ir_cut/data/mc_q5_pooled.csv（source, trial, mtf120）
% 判据：DiffMTFAverage，后焦补偿器 ±0.2 mm，Q5 等级（胶合面 S6/S7 收紧到 ±0.01875）
clear; clc; close all;

rootDir = 'D:\Zemax-mcp';
csvFile = fullfile(rootDir, 'zemax-ADAS','no_ir_cut','data', 'mc_q5_pooled.csv');
figDir  = fullfile(rootDir, 'zemax-ADAS','no_ir_cut','figs');
if ~exist(figDir, 'dir'); mkdir(figDir); end

spec = 0.35;          % MTF@120 验收下限

%% ---- 读数据 ----
T = readtable(csvFile);
x = T.mtf120;
x = x(~isnan(x));
n = numel(x);

mu   = mean(x);
sd   = std(x);
cpk  = (mu - spec) / (3 * sd);
yld  = mean(x >= spec);
sigs = (mu - spec) / sd;

%% ---- bootstrap 95% CI（良率 + 各规格点）----
thr   = (0.32:0.01:0.46)';
B     = 2000;
rng(42);
yThr  = zeros(numel(thr), 1);
boot  = zeros(B, numel(thr));
for b = 1:B
    idx = randi(n, n, 1);
    xb  = x(idx);
    boot(b, :) = mean(xb >= thr', 1);
end
for k = 1:numel(thr)
    yThr(k) = mean(x >= thr(k));
end
ciLo = prctile(boot, 2.5, 1)';
ciHi = prctile(boot, 97.5, 1)';

yCI = prctile(mean(x(randi(n, n, B)) >= spec, 1), [2.5 97.5]);

p5  = prctile(x, 5);
p50 = prctile(x, 50);
p95 = prctile(x, 95);

fprintf('N=%d\n', n);
fprintf('mean=%.4f  sd=%.4f  min=%.4f\n', mu, sd, min(x));
fprintf('P5=%.4f  P50=%.4f  P95=%.4f\n', p5, p50, p95);
fprintf('yield(>=%.2f)=%.2f%%  95%%CI=[%.2f%%, %.2f%%]\n', spec, 100*yld, 100*yCI(1), 100*yCI(2));
fprintf('CPK=%.2f  (%.2f sigma)\n', cpk, sigs);
fprintf('--- 良率 vs 规格 ---\n');
for k = 1:numel(thr)
    fprintf('  MTF>=%.2f  %6.2f%%  [%5.2f, %5.2f]\n', thr(k), 100*yThr(k), 100*ciLo(k), 100*ciHi(k));
end

%% ---- 出图 ----
fig = figure('Visible', 'off', 'Color', 'w', 'Position', [80 80 1180 480]);

% (a) 直方图 + 正态拟合
ax1 = subplot(1, 2, 1);
hold(ax1, 'on');
h = histogram(ax1, x, 28, 'Normalization', 'pdf', ...
    'FaceColor', [0.35 0.58 0.80], 'EdgeColor', [1 1 1], 'FaceAlpha', 0.85);
xs = linspace(min(x) - 0.02, max(x) + 0.02, 400);
plot(ax1, xs, normpdf(xs, mu, sd), 'k-', 'LineWidth', 1.6);
yl = ylim(ax1);
xlim(ax1, [min(x) - 0.025, max(x) + 0.02]);
plot(ax1, [spec spec], yl, 'r--', 'LineWidth', 1.8);
plot(ax1, [mu mu], yl, 'k:', 'LineWidth', 1.2);
text(ax1, spec + 0.004, yl(2)*0.06, sprintf('规格 %.2f', spec), ...
    'Color', 'r', 'FontSize', 9, 'HorizontalAlignment', 'left');
text(ax1, mu + 0.004, yl(2)*0.78, sprintf('均值 %.4f', mu), ...
    'Color', 'k', 'FontSize', 9, 'HorizontalAlignment', 'left');
text(ax1, min(x) + 0.004, yl(2)*0.72, sprintf('最差 %.3f', min(x)), ...
    'Color', [0.55 0.10 0.10], 'FontSize', 9, 'HorizontalAlignment', 'left');
xlabel(ax1, 'MTF@120 lp/mm（复色，全视场 T/S 平均）');
ylabel(ax1, '概率密度');
title(ax1, sprintf('蒙特卡洛分布（两批各 500 次，N=%d）  良率 %.1f%%  CPK=%.2f', n, 100*yld, cpk));
legend(ax1, {'样本分布', '正态拟合', '验收规格', '样本均值'}, ...
    'Location', 'northeast', 'Box', 'off');
grid(ax1, 'on'); box(ax1, 'off');

% (b) 良率 vs 规格（含 95% CI 带）
ax2 = subplot(1, 2, 2);
hold(ax2, 'on');
fill(ax2, [thr; flipud(thr)], [ciLo; flipud(ciHi)] * 100, [0.75 0.85 0.95], ...
    'EdgeColor', 'none', 'FaceAlpha', 0.9);
plot(ax2, thr, yThr * 100, '-o', 'Color', [0.10 0.32 0.60], ...
    'MarkerFaceColor', [0.10 0.32 0.60], 'MarkerSize', 4, 'LineWidth', 1.6);
plot(ax2, [spec spec], [0 100], 'r--', 'LineWidth', 1.4);
yline(ax2, 90, ':', 'Color', [0.4 0.4 0.4], 'LineWidth', 1.2);
yline(ax2, 100, '-', 'Color', [0.6 0.6 0.6], 'LineWidth', 0.8);
text(ax2, spec + 0.002, 80, '规格 0.35', 'Color', 'r', 'FontSize', 9);
text(ax2, thr(1) + 0.002, 91, '90% 良率线', 'Color', [0.4 0.4 0.4], 'FontSize', 8);
xlabel(ax2, 'MTF@120 验收下限');
ylabel(ax2, '良率 (%)');
title(ax2, '良率—规格曲线（阴影 = bootstrap 95% CI，B=2000）');
xlim(ax2, [thr(1) thr(end)]);
ylim(ax2, [78 101.5]);
grid(ax2, 'on'); box(ax2, 'off');

% 统一样式
set(findall(fig, '-property', 'FontName'), 'FontName', 'Microsoft YaHei');
set(findall(fig, '-property', 'FontSize'), 'FontSize', 9);
set(findall(fig, 'Type', 'axes'), 'LineWidth', 0.8, 'GridAlpha', 0.15);

outPng = fullfile(figDir, 'mc_yield_q5_20261119.png');
exportgraphics(fig, outPng, 'Resolution', 300);
close(fig);
fprintf('saved: %s\n', outPng);
