% plot_athermal_R11_20261122.m
% 长后焦 v8 · 末片半球整改版 · 无热化（-40 ~ +125 degC，铝镜筒 23.6 ppm/K）
%   上：离焦量 vs 温度（不调焦）/ 调焦后所需 sensor 位移，标瑞利焦深带
%   下：调焦后边缘视场 MTF@120 vs 温度，与常温对标
% 数据：data/athermal_R11_20261122.csv
% 输出：figs/athermal_defocus.png（300 dpi）

clear; close all;

base = fileparts(mfilename('fullpath'));
if isempty(base); base = pwd; end
dat  = fullfile(base,'data');
out  = fullfile(base,'figs');
if ~exist(out,'dir'); mkdir(out); end

T = readtable(fullfile(dat,'athermal_R11_20261122.csv'));
T = sortrows(T,'temp_c');            % 按温度升序，否则折线会按 CSV 行序乱连
Tc    = T.temp_c;
def   = T.defocus_um;          % z_focus - z_sensor（正 = 焦点比 sensor 更靠后）
trav  = def;                   % 让 sensor 与焦点重合所需的位移（正 = 后移）
mtf   = T.edge_mtf_min_120;
rms   = T.spot_rms_max_um;

dof = 2.3;                     % 瑞利焦深 +/-2.3 um @ F/1.4
[~, i0] = min(abs(Tc-25));
mtf25 = mtf(i0);
span  = max(trav) - min(trav);
drop  = (min(mtf)-mtf25)/mtf25*100;

fprintf('调焦行程区间: %+.1f ~ %+.1f um, 跨度 %.1f um\n', min(trav), max(trav), span);
fprintf('调焦后边缘 MTF@120: %.4f ~ %.4f (常温 %.4f), 最大跌幅 %.1f %%\n', ...
        min(mtf), max(mtf), mtf25, -drop);
fprintf('调焦后 spot RMS max: %.3f ~ %.3f um\n', min(rms), max(rms));

fig = figure('Color','w','Position',[60 60 980 760],'Visible','off');

% ---------------- (a) 离焦与调焦量 ----------------
subplot(2,1,1); hold on; box on; grid on;
fill([min(Tc) max(Tc) max(Tc) min(Tc)], [-dof -dof dof dof], ...
     [0.00 0.45 0.74], 'FaceAlpha',0.12, 'EdgeColor','none');
yline(0,'-','Color',[0.3 0.3 0.3],'LineWidth',1.0);
plot(Tc, trav, '-o', 'Color',[0.85 0.33 0.10], 'LineWidth',1.8, ...
     'MarkerSize',6, 'MarkerFaceColor','w');
text(55, dof+1.6, sprintf('瑞利焦深 ±%.1f µm', dof), ...
     'FontSize',8.5,'Color',[0.00 0.35 0.60]);
text(min(Tc)+2, trav(1)-5.0, sprintf('−40 ℃：%+.1f µm（后移）', trav(1)), ...
     'FontSize',9,'Color',[0.85 0.33 0.10]);
text(max(Tc)-2, trav(end)+5.0, sprintf('+125 ℃：%+.1f µm（前移）', trav(end)), ...
     'FontSize',9,'Color',[0.85 0.33 0.10],'HorizontalAlignment','right');
xlabel('温度 (°C)','FontSize',10);
ylabel('所需 sensor 位移 (µm)','FontSize',10);
legend({'焦深带','零位','调焦量（= 不调焦离焦）'}, 'Location','northeast','FontSize',9,'Box','off');
title(sprintf('无热化：调焦行程 %.1f µm（%+.0f ~ %+.0f µm），铝镜筒 23.6 ppm/K', ...
      span, min(trav), max(trav)),'FontSize',11);
set(gca,'FontSize',9,'LineWidth',0.8,'GridAlpha',0.15,'XLim',[min(Tc)-2 max(Tc)+2]);

% ---------------- (b) 调焦后 MTF ----------------
subplot(2,1,2); hold on; box on; grid on;
yline(mtf25*0.8,'--','Color',[0.6 0.6 0.6],'LineWidth',1.1);
yline(mtf25,'-.','Color',[0.10 0.45 0.10],'LineWidth',1.2);
plot(Tc, mtf, '-o', 'Color',[0.47 0.67 0.19], 'LineWidth',1.7, ...
     'MarkerSize',6, 'MarkerFaceColor','w');
text(min(Tc)+3, mtf25*0.8+0.006, '常温 × 0.8（-20% 判据线）', 'FontSize',8.5,'Color',[0.45 0.45 0.45]);
text(min(Tc)+3, mtf25+0.006, sprintf('常温 %.3f', mtf25), 'FontSize',8.5,'Color',[0.10 0.45 0.10]);
xlabel('温度 (°C)','FontSize',10);
ylabel('边缘视场 MTF @120 lp/mm','FontSize',10);
title(sprintf('调焦后边缘 MTF：%.3f ~ %.3f，相对常温最大跌幅 %.1f %%', min(mtf), max(mtf), -drop), 'FontSize',11);
set(gca,'FontSize',9,'LineWidth',0.8,'GridAlpha',0.15,'XLim',[min(Tc)-2 max(Tc)+2]);

set(findall(fig,'-property','FontName'),'FontName','Microsoft YaHei');
exportgraphics(fig, fullfile(out,'athermal_defocus.png'), 'Resolution', 300);
close(fig);
fprintf('wrote %s\n', fullfile(out,'athermal_defocus.png'));
