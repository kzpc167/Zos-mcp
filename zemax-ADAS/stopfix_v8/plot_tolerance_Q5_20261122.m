% plot_tolerance_Q5_20261122.m
% 长后焦 v8 · 末片半球整改版（L7 R = -7.100）Q5 公差
%   判据 DiffMTFAverage @ 120 lp/mm，500 次蒙特卡洛，后焦补偿器
%
% 刻度说明（重要）：
%   公差向导按「XY 对称」模板生成 9 个视场，(0,±12.2°)、(±12.2°,0) 4 个 + (0,±17.43°)、(±17.43°,0) 4 个。
%   本设计像圈 2×4.668 mm，17.43° 轴上视场的像高 4.72 mm 已出像面，4 个视场 MTF 恒为 0，
%   于是报告里的 名义/均值/分位 都是「9 视场上取平均」= 5/9 ×（5 个有效视场的平均）。
%   本脚本统一乘 9/5 折算回 5 个有效视场的平均，与设计口径同量级；原始值保留在 x_raw。
%   折算只改刻度，不改任何相对结论（劣化百分比、灵敏度排序、相对规格良率全部不变）。
%
% 数据：data/tolerance_Q5_MC500.csv、data/tolerance_sensitivity.csv
% 输出：figs/tolerance_Q5_yield.png（300 dpi）

clear; close all;

base = fileparts(mfilename('fullpath'));
if isempty(base); base = pwd; end
dat  = fullfile(base,'data');
out  = fullfile(base,'figs');
if ~exist(out,'dir'); mkdir(out); end

T = readtable(fullfile(dat,'tolerance_Q5_MC500.csv'));
x_raw = T.mtf_avg_120lpmm(:);      % 公差报告原始刻度：9 视场均值，其中 4 个视场落在像圈外、恒为 0
x     = T.mtf_avg_corrected(:);    % ×9/5：折算成「5 个有效视场」的平均（与设计口径同量级）
N = numel(x);
mu = mean(x);  sg = std(x,0);
nom = 0.35340961*9/5;              % 名义：0.3534 × 9/5 = 0.6361

spec_hi = nom*0.85;   % 名义 -15%（收紧档）
spec_lo = nom*0.80;   % 名义 -20%（skill 推荐档）
spec_25 = nom*0.75;   % 名义 -25%（放宽档）
y_hi = mean(x > spec_hi)*100;
y_lo = mean(x > spec_lo)*100;
y_25 = mean(x > spec_25)*100;
cpk  = (mu - spec_hi)/(3*sg);

fprintf('N = %d\n', N);
fprintf('原始刻度：nominal = %.5f  mean = %.5f  sd = %.5f  min = %.5f  max = %.5f\n', ...
        0.35340961, mean(x_raw), std(x_raw,0), min(x_raw), max(x_raw));
fprintf('有效视场刻度：nominal = %.4f  mean = %.4f  sd = %.4f  min = %.4f  max = %.4f\n', ...
        nom, mu, sg, min(x), max(x));
fprintf('P1 = %.4f  P5 = %.4f  P10 = %.4f  P50 = %.4f  P90 = %.4f\n', ...
        prctile_local(x,1), prctile_local(x,5), prctile_local(x,10), ...
        prctile_local(x,50), prctile_local(x,90));
fprintf('yield > %.4f (-15%%): %.1f %%   (CPK = %.2f)\n', spec_hi, y_hi, cpk);
fprintf('yield > %.4f (-20%%): %.1f %%   (CPK = %.2f)\n', spec_lo, y_lo, (mu-spec_lo)/(3*sg));
fprintf('yield > %.4f (-25%%): %.1f %%   (CPK = %.2f)\n', spec_25, y_25, (mu-spec_25)/(3*sg));

fig = figure('Color','w','Position',[60 60 1060 760],'Visible','off');

% ---------------- (a) 蒙特卡洛分布 ----------------
subplot(2,1,1); hold on; box on; grid on;
edges = linspace(min(x)-0.005, max(x)+0.005, 31);
hb = histogram(x, edges, 'FaceColor',[0.00 0.45 0.74], 'EdgeColor','w', 'FaceAlpha',0.85);
% 正态拟合（不依赖统计工具箱）
xx = linspace(min(x), max(x), 400);
pdf = N*(edges(2)-edges(1)) * exp(-(xx-mu).^2/(2*sg^2))/(sg*sqrt(2*pi));
hp = plot(xx, pdf, '-', 'Color',[0.85 0.33 0.10], 'LineWidth',1.8);
yl = ylim;
xline(spec_hi,'-','Color',[0.75 0.10 0.10],'LineWidth',1.6);
xline(spec_lo,'--','Color',[0.55 0.55 0.55],'LineWidth',1.3);
xline(mu,'-.','Color',[0.10 0.45 0.10],'LineWidth',1.4);
legend([hb hp], {'蒙特卡洛样本','正态拟合'}, 'Location','northwest', ...
       'FontSize',8.5,'Box','off');
info = { sprintf('名义            %.3f', nom), ...
         sprintf('均值 / σ       %.3f / %.3f', mu, sg), ...
         sprintf('最差 / 最佳   %.3f / %.3f', min(x), max(x)), ...
         sprintf('良率 −15%%    %.3f → %.1f%%', spec_hi, y_hi), ...
         sprintf('良率 −20%%    %.3f → %.1f%%', spec_lo, y_lo), ...
         sprintf('良率 −25%%    %.3f → %.1f%%', spec_25, y_25) };
text(0.965, 0.95, info, 'Units','normalized', ...
     'HorizontalAlignment','right', 'VerticalAlignment','top', ...
     'FontSize',8.5, 'BackgroundColor','w', 'EdgeColor',[0.75 0.75 0.75], 'Margin',4);
xlabel('全视场平均 MTF @ 120 lp/mm（5 个有效视场，T/S 平均）','FontSize',10);
ylabel('样本数','FontSize',10);
title(sprintf('Q5 公差蒙特卡洛 (N = %d)：名义 %.3f，均值 %.3f，σ %.3f，最差 %.3f', ...
      N, nom, mu, sg, min(x)),'FontSize',11);
set(gca,'FontSize',9,'LineWidth',0.8,'GridAlpha',0.15,'XLim',[min(x)-0.005 max(x)+0.005]);

% ---------------- (b) 灵敏度排序 ----------------
S = readtable(fullfile(dat,'tolerance_sensitivity.csv'));
lbl = cell(height(S),1);
for k = 1:height(S)
    lbl{k} = sprintf('%s %s  (±%g)', S.type{k}, S.target{k}, S.tol_abs(k));
end
subplot(2,1,2); hold on; box on; grid on;
yy = flipud(S.impact_corrected);
barh(1:height(S), yy, 0.65, 'FaceColor',[0.47 0.67 0.19], 'EdgeColor','none');
set(gca,'YTick',1:height(S),'YTickLabel',flipud(lbl),'FontSize',8.5);
xlabel('单项公差引起的 MTF 劣化（Δ 全视场平均 @120）','FontSize',10);
title(sprintf('Q5 公差灵敏度 Top 10（名义 %.3f；每项单独作用时的劣化）', nom),'FontSize',11);
xlim([0 max(S.impact_corrected)*1.18]);
for k = 1:height(S)
    text(yy(k)+max(S.impact_corrected)*0.012, k, sprintf('%.4f', yy(k)), 'FontSize',8,'VerticalAlignment','middle');
end
set(gca,'LineWidth',0.8,'GridAlpha',0.15);

set(findall(fig,'-property','FontName'),'FontName','Microsoft YaHei');
exportgraphics(fig, fullfile(out,'tolerance_Q5_yield.png'), 'Resolution', 300);
close(fig);
fprintf('wrote %s\n', fullfile(out,'tolerance_Q5_yield.png'));

% ---------- 局部函数 ----------
function q = prctile_local(v, p)
    v = sort(v(:));  n = numel(v);
    idx = max(1, min(n, round(p/100*n)));
    q = v(idx);
end
