% plot_mtf_R11_20261122.m
% 长后焦 v8 · 末片半球专项（L7 前表面 R = -7.100，r/R = 0.704）
% 复色 FFT MTF，0-120 lp/mm，5 视场 T/S + 衍射极限
% 数据：data/mtf_curves_R11_20261122.csv（由 analysis/fft_mtf.txt 解析）
% 输出：figs/mtf_120.png（300 dpi）

clear; close all;

base = fileparts(mfilename('fullpath'));
if isempty(base); base = pwd; end
dat  = fullfile(base,'data');
out  = fullfile(base,'figs');
if ~exist(out,'dir'); mkdir(out); end

D  = readmatrix(fullfile(dat,'mtf_curves_R11_20261122.csv'),'NumHeaderLines',1);
f  = D(:,1);
DL = D(:,2);
T  = D(:,3:2:11);   % f1..f5 子午
S  = D(:,4:2:12);   % f1..f5 弧矢

nF  = size(T,2);
lbl = {'0.00° 轴上','8.75° Y','15.00° Y','7.5°/4.3° 对角','15.1°/8.7° 全视场'};
col = [0.00 0.45 0.74; 0.85 0.33 0.10; 0.47 0.67 0.19; ...
       0.49 0.18 0.56; 0.93 0.69 0.13];

fig = figure('Color','w','Position',[80 80 900 620],'Visible','off');
hold on; box on; grid on;

hDL = plot(f, DL, '-', 'Color',[0 0 0], 'LineWidth',1.6);

h = gobjects(nF,1);
for k = 1:nF
    h(k) = plot(f, T(:,k), '-',  'Color',col(k,:), 'LineWidth',1.5);
    plot(f, S(:,k), '--', 'Color',col(k,:), 'LineWidth',1.1, 'HandleVisibility','off');
end

xline(120,'k:','120 lp/mm','LabelVerticalAlignment','bottom','LabelHorizontalAlignment','right', ...
      'FontSize',8,'HandleVisibility','off');
yline(0.5,'--','Color',[0.6 0.6 0.6],'LineWidth',1.0,'HandleVisibility','off');
text(2,0.515,'规格线 0.5','FontSize',8,'Color',[0.45 0.45 0.45]);

set(gca,'FontSize',10,'LineWidth',0.9,'GridAlpha',0.15, ...
        'XLim',[0 120],'YLim',[0 1],'XTick',0:20:120,'YTick',0:0.1:1);
xlabel('空间频率 (lp/mm)','FontSize',11);
ylabel('MTF（复色 486–656 nm）','FontSize',11);
title('15 mm F/1.4 长后焦 v8 · 末片 R = −7.100（r/R = 0.704）· FFT MTF','FontSize',11.5);

lg = legend([hDL; h], [{'衍射极限'}; lbl(:)], 'Location','southwest','FontSize',9,'Box','off');
lg.ItemTokenSize = [18 9];
set(findall(fig,'-property','FontName'),'FontName','Microsoft YaHei');

exportgraphics(fig, fullfile(out,'mtf_120.png'), 'Resolution', 300);
close(fig);

fprintf('wrote %s\n', fullfile(out,'mtf_120.png'));
fprintf('MTF@120  T/S:\n');
for k = 1:nF
    fprintf('  %-18s %.4f / %.4f\n', lbl{k}, T(end,k), S(end,k));
end
fprintf('  %-18s %.4f\n','衍射极限',DL(end));
fprintf('最差（120 lp/mm）: %.4f\n', min([T(end,:) S(end,:)]));
fprintf('最差（ 60 lp/mm）: %.4f\n', min([T(61,:) S(61,:)]));
