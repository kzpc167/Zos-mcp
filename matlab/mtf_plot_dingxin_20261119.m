%% 终版 15 mm F/1.4 定心版 —— 复色衍射 MTF 曲线（0~120 lp/mm 完整采样）
% 数据：OpticStudio 原生 FFT MTF 文本导出 layouts/no_ir_cut/analysis/fft_mtf.txt
%       → tmp/parse_mtf_curves.py → matlab/data/mtf_curves_final.csv
% 口径：复色 0.486~0.656 µm，像面，5 个视场，子午/弧矢
clear; clc; close all;

rootDir = 'D:\Zemax-mcp';
csvFile = fullfile(rootDir, 'matlab', 'data', 'mtf_curves_final.csv');
figDir  = fullfile(rootDir, 'zemax-ADAS', 'layouts', 'no_ir_cut');
if ~exist(figDir, 'dir'); mkdir(figDir); end

T  = readtable(csvFile);
f  = T.freq;

names  = {'0.00° 轴上', '8.75° Y', '15.00° Y', '8.60° 对角', '17.43° 全视场'};
colors = [0.00 0.45 0.74;
          0.85 0.33 0.10;
          0.47 0.67 0.19;
          0.49 0.18 0.56;
          0.93 0.69 0.13];

Tcurves = {T.F1_T, T.F2_T, T.F3_T, T.F4_T, T.F5_T};
Scurves = {T.F1_S, T.F2_S, T.F3_S, T.F4_S, T.F5_S};

fig = figure('Visible', 'off', 'Color', 'w', 'Position', [80 80 1480 740]);
ax  = axes(fig); hold(ax, 'on');

hD = plot(ax, f, T.diff_T, 'k:', 'LineWidth', 2.0);
h  = gobjects(5, 2);
for i = 1:5
    h(i,1) = plot(ax, f, Tcurves{i}, '-',  'Color', colors(i,:), 'LineWidth', 1.6);
    h(i,2) = plot(ax, f, Scurves{i}, '--', 'Color', colors(i,:), 'LineWidth', 1.2);
end

xline(ax, 120, 'Color', [0.45 0.45 0.45], 'LineWidth', 1.0, 'LineStyle', '-.');
xlim(ax, [0 120]);
ylim(ax, [0 1.02]);

% 逐视场 @120 读数表
vT = cellfun(@(v) v(end), Tcurves);
vS = cellfun(@(v) v(end), Scurves);
txt = {'MTF @120 lp/mm  (T / S)'};
for i = 1:5
    txt{end+1} = sprintf('%-14s %.3f / %.3f', names{i}, vT(i), vS(i));
end
txt{end+1} = sprintf('%-14s %.3f', '衍射极限', T.diff_T(end));
text(ax, 2, 0.34, txt, 'FontSize', 9, 'VerticalAlignment', 'top', ...
    'BackgroundColor', [1 1 1], 'EdgeColor', [0.85 0.85 0.85], 'Margin', 6);

xlabel(ax, '空间频率 (lp/mm)');
ylabel(ax, '调制传递函数 MTF');
title(ax, '复色衍射 MTF（0.486–0.656 \mum，像面）—— 终版定心设计');

grid(ax, 'on');
box(ax, 'off');

% 单图例：5 个视场（实线=子午）+ T/S/极限说明放在标题区
lg = legend(ax, h(:,1), strcat(names, '  子午T'), 'Location', 'eastoutside');
set(lg, 'Box', 'off', 'FontSize', 9);
text(ax, 60, 0.06, '实线 = 子午 T　虚线 = 弧矢 S　点线 = 衍射极限', ...
    'FontSize', 9, 'Color', [0.35 0.35 0.35], 'HorizontalAlignment', 'center');

set(findall(fig, '-property', 'FontName'), 'FontName', 'Microsoft YaHei');
set(findall(fig, '-property', 'FontSize'), 'FontSize', 10);
set(ax, 'LineWidth', 0.9, 'GridAlpha', 0.15);

outPng = fullfile(figDir, 'MTF.png');
exportgraphics(fig, outPng, 'Resolution', 300);
close(fig);

fprintf('saved: %s\n', outPng);
fprintf('MTF@120  T / S\n');
for i = 1:5
    fprintf('  F%d %-14s %.4f / %.4f\n', i, names{i}, vT(i), vS(i));
end
fprintf('  衍射极限        %.4f\n', T.diff_T(end));
fprintf('  平均(T/S)       %.4f\n', mean([vT vS]));
