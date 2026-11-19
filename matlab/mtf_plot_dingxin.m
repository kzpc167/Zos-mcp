%% MTF 出图：车载长焦前摄 15mm F/1.4 · 弯月替换定心版（单组态）
% 数据来源：mcp__zemax-opticstudio__get_mtf_curve（复色 0.486/0.588/0.656 um，max_frequency=240）
% 曲线：5 个视场 T/S 共 10 条 + 衍射极限；标注规格频率 120 lp/mm
% 运行：matlab -batch "run('D:/Zemax-mcp/matlab/mtf_plot_dingxin.m')"

clear; close all;

root    = 'D:\Zemax-mcp';
csvPath = fullfile(root, 'matlab', 'data', 'mtf_curve_dingxin.csv');
outDir  = fullfile(root, 'zemax-ADAS', 'layouts');
if ~exist(outDir, 'dir'); mkdir(outDir); end

T = readtable(csvPath);
f  = T.freq_lpmm;

names  = {'0.00° (轴上)', '8.75° (0.58H)', '15.0° (1.00H)', ...
          '(7.5,4.3)° (0.29H)', '(15.1,8.7)° (对角)'};
colors = [0.00 0.00 0.00;   % 轴上 黑
          0.00 0.45 0.70;   % 8.75 蓝
          0.85 0.33 0.10;   % 15 橙红
          0.00 0.62 0.45;   % (7.5,4.3) 绿
          0.49 0.18 0.56];  % 对角 紫

fig = figure('Visible', 'off', 'Color', 'w', 'Position', [100 100 1000 620]);
hold on; grid on; box on;

% 衍射极限
hDiff = plot(f, T.dl, '-.', 'Color', [0.45 0.45 0.45], 'LineWidth', 1.4);

h = gobjects(5, 2);
for k = 1:5
    h(k,1) = plot(f, T{:, 2*k},   '-',  'Color', colors(k,:), 'LineWidth', 1.4); % T
    h(k,2) = plot(f, T{:, 2*k+1}, '--', 'Color', colors(k,:), 'LineWidth', 1.1); % S
end

% 规格频率
yl = [0 1];
plot([120 120], yl, ':', 'Color', [0.7 0.1 0.1], 'LineWidth', 1.2);
text(121.5, 0.955, '规格 120 lp/mm', 'FontSize', 8, 'Color', [0.7 0.1 0.1]);

xlabel('空间频率 (lp/mm)');
ylabel('调制传递函数 MTF');
title({'FFT MTF · 车载长焦前摄 15mm F/1.4（5 片 · 删 L5 定心版，单组态）', ...
       '复色 0.486/0.588/0.656 μm　实线=T（子午）　虚线=S（弧矢）'}, 'FontSize', 10);
xlim([0 240]); ylim(yl);

lgObj = [h(:,1); h(:,2); hDiff];
lgTxt = cell(11,1);
for k = 1:5
    lgTxt{k}   = [names{k} ' T'];
    lgTxt{k+5} = [names{k} ' S'];
end
lgTxt{11} = '衍射极限 (diffraction limit)';
legend(lgObj, lgTxt, 'Location', 'northeast', 'FontSize', 7.5, 'NumColumns', 1);

set(gca, 'FontSize', 10, 'LineWidth', 0.8, 'GridAlpha', 0.15);
set(findall(fig, '-property', 'FontName'), 'FontName', 'Microsoft YaHei');

outPng = fullfile(outDir, 'MTF.png');
exportgraphics(fig, outPng, 'Resolution', 300);

% 打印 120 lp/mm 的插值值，供报告核对
m120 = interp1(f, [T.f1T T.f1S T.f2T T.f2S T.f3T T.f3S T.f4T T.f4S T.f5T T.f5S], 120);
fprintf('MTF@120lp/mm  T1=%.3f S1=%.3f  T2=%.3f S2=%.3f  T3=%.3f S3=%.3f  T4=%.3f S4=%.3f  T5=%.3f S5=%.3f\n', m120);
fprintf('saved: %s\n', outPng);
close all;
