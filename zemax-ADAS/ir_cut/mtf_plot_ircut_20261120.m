%% 15 mm F/1.4 定心版 + IR-CUT/CG —— 原生复色衍射 MTF 曲线
% 数据：OpticStudio 原生 FFT MTF 文本导出
%       zemax-ADAS/ir_cut/figs/analysis/fft_mtf.txt（UTF-16，制表符分隔）
% 口径：复色 0.486–0.656 µm，像面，5 个视场（角度定义），子午/弧矢
% 结构：第 1 块 = 衍射极限，第 2–6 块 = 视场 1–5，每块 121 行（0–120 lp/mm）
clear; clc; close all;

rootDir = 'D:\Zemax-mcp';
srcFile = fullfile(rootDir, 'zemax-ADAS', 'ir_cut','figs', 'analysis', 'fft_mtf.txt');
figDir  = fullfile(rootDir, 'zemax-ADAS', 'ir_cut','figs');

%% 1. 解析原生文本（按字节读，UTF-16LE 带 BOM）
fid = fopen(srcFile, 'rb');
assert(fid > 0, '打不开 %s', srcFile);
b = fread(fid, inf, 'uint8=>uint8');
fclose(fid);
if numel(b) > 2 && b(1) == 255 && b(2) == 254
    b = b(3:end);
end
u = uint16(b(1:2:end)) + 256 * uint16(b(2:2:end));
lines = splitlines(string(char(u(:)')));

blocks = {};
cur = zeros(0, 3);
for k = 1:numel(lines)
    parts = strtrim(split(lines(k), sprintf('\t')));
    if numel(parts) == 3
        v = str2double(parts);
        if all(~isnan(v))
            cur(end+1, :) = v; %#ok<SAGROW>
            continue
        end
    end
    if ~isempty(cur)
        blocks{end+1} = cur; %#ok<SAGROW>
        cur = zeros(0, 3);
    end
end
if ~isempty(cur)
    blocks{end+1} = cur;
end

assert(numel(blocks) == 6, '应为 6 块（衍射极限 + 5 视场），实际 %d', numel(blocks));
assert(all(cellfun(@(x) size(x, 1), blocks) == 121), '每块应为 121 行');

diffT = blocks{1}(:, 2);
f     = blocks{1}(:, 1);
T = zeros(121, 5);
S = zeros(121, 5);
for i = 1:5
    T(:, i) = blocks{i+1}(:, 2);
    S(:, i) = blocks{i+1}(:, 3);
end

%% 2. 关键读数（120 lp/mm）
[~, i120] = min(abs(f - 120));
vT = T(i120, :);
vS = S(i120, :);
d120 = diffT(i120);

fprintf('MTF @ %.0f lp/mm  (T / S)\n', f(i120));
fprintf('  衍射极限   %.4f\n', d120);
names = {'0.00° 轴上', '8.75° Y', '15.00° Y', '8.65° 对角', '17.43° 全视场'};
for i = 1:5
    fprintf('  F%d %-12s %.4f / %.4f\n', i, names{i}, vT(i), vS(i));
end
vals = [vT(:); vS(:)];
[mn, idx] = min(vals);
if idx <= 5
    fi = idx; dirTxt = '子午';
else
    fi = idx - 5; dirTxt = '弧矢';
end
fprintf('  最差 %.4f（%s，%s）\n', mn, names{fi}, dirTxt);

%% 3. 出图
colors = [0.00 0.45 0.74;
          0.85 0.33 0.10;
          0.47 0.67 0.19;
          0.49 0.18 0.56;
          0.93 0.69 0.13];

fig = figure('Visible', 'off', 'Color', 'w', 'Position', [80 80 1480 740]);
ax  = axes(fig); hold(ax, 'on');

plot(ax, f, diffT, 'k:', 'LineWidth', 2.0);
hh = gobjects(5, 2);
for i = 1:5
    hh(i, 1) = plot(ax, f, T(:, i), '-',  'Color', colors(i, :), 'LineWidth', 1.6);
    hh(i, 2) = plot(ax, f, S(:, i), '--', 'Color', colors(i, :), 'LineWidth', 1.2);
end

xline(ax, 120, 'Color', [0.45 0.45 0.45], 'LineWidth', 1.0, 'LineStyle', '-.');
xlim(ax, [0 120]);
ylim(ax, [0 1.02]);

txt = {sprintf('MTF @%.0f lp/mm  (T / S)', f(i120))};
for i = 1:5
    txt{end+1} = sprintf('%-13s %.3f / %.3f', names{i}, vT(i), vS(i)); %#ok<SAGROW>
end
txt{end+1} = sprintf('%-13s %.3f', '衍射极限', d120);
text(ax, 2, 0.36, txt, 'FontSize', 9, 'VerticalAlignment', 'top', ...
    'BackgroundColor', [1 1 1], 'EdgeColor', [0.85 0.85 0.85], 'Margin', 6);

xlabel(ax, '空间频率 (lp/mm)');
ylabel(ax, '调制传递函数 MTF');
title(ax, '复色衍射 MTF（0.486–0.656 \mum）—— 加 IR-CUT 版（TOTR 30.0 mm）');

grid(ax, 'on');
box(ax, 'off');
lg = legend(ax, hh(:, 1), strcat(names, '  子午'), 'Location', 'eastoutside');
set(lg, 'Box', 'off', 'FontSize', 9);
text(ax, 60, 0.05, '实线 = 子午 T　虚线 = 弧矢 S　点线 = 衍射极限', ...
    'FontSize', 9, 'Color', [0.35 0.35 0.35], 'HorizontalAlignment', 'center');

set(findall(fig, '-property', 'FontName'), 'FontName', 'Microsoft YaHei');
set(findall(fig, '-property', 'FontSize'), 'FontSize', 10);
set(ax, 'LineWidth', 0.9, 'GridAlpha', 0.15);

outPng = fullfile(figDir, 'MTF_IRcut.png');
exportgraphics(fig, outPng, 'Resolution', 300);
close(fig);
fprintf('已输出 %s\n', outPng);
