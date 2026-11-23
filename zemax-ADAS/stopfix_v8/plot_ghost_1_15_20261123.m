% plot_ghost_1_15_20261123.m
% 长后焦 v8 · R11 交付版：Ghost Focus Generator（二次反射 1↔15）结果分析
%
% 数据来源：鬼影分析1-15.txt（Zemax GUI「鬼像焦点生成器」导出，UTF-16LE）
%           由 python 解析为 data/ghost_1_15_bounce.csv（91 条 = C(14,2)，光阑虚面已自动跳过）
%
% 判读口径（重要）：
%   1) 本文件只有几何量，没有镀膜反射率 → 不能算 GISET，只能做几何筛查排序。
%   2) Zemax 输出的 RMS = 0.00 不是「完美焦点」，是追迹失败（官方英文说明）。
%      本脚本把 rms_valid=0 的 18 条单独标记，不参与锐度排序。
%   3) 「相对峰值照度」按 I_rel ∝ 1/RMS² 计算（反射率相同、光瞳通过率未建模），
%      只用于同一份数据内部的相对排序，绝对值不可外推。
%   4) S14（窗口后表面）厚度 = 0.0000 mm，与 S15（像面）重合，所以
%      「15 然后 13/9」与「14 然后 13/9」是同一物理路径的数值重复，解读时合并。
%
% 输入：data/ghost_1_15_bounce.csv
% 输出：figs/ghost_1_15_analysis.png（300 dpi）、analysis/ghost_1_15_summary.txt

clear; close all;

base = fileparts(mfilename('fullpath'));
if isempty(base); base = pwd; end
dat = fullfile(base,'data');
fig_dir = fullfile(base,'figs');
ana_dir = fullfile(base,'analysis');
if ~exist(fig_dir,'dir'); mkdir(fig_dir); end
if ~exist(ana_dir,'dir'); mkdir(ana_dir); end

T = readtable(fullfile(dat,'ghost_1_15_bounce.csv'));
N = height(T);

% ---------- 面号 → 元件名 ----------
lbl_map = { ...
  1,'L1前',2,'L1后',3,'L2前',4,'L2后',5,'光阑', ...
  6,'L3前',7,'胶合面',8,'L4后',9,'L6前',10,'L6后', ...
  11,'L7前',12,'L7后',13,'窗口前',14,'窗口后',15,'像面'};
name_of = @(k) lbl_map{2*find([lbl_map{1:2:end}]==k,1)};
path_name = arrayfun(@(a,b) sprintf('%s%d→%s%d', name_of(a),a,name_of(b),b), ...
                     T.surf_first, T.surf_second, 'UniformOutput', false);
short_name = arrayfun(@(a,b) sprintf('%d→%d',a,b), T.surf_first, T.surf_second, ...
                      'UniformOutput', false);

valid = T.rms_valid == 1;
rms   = T.rms_radius_mm;
focus = T.focus_dist_mm;
pupil = T.pupil_dist_mm;
efl   = T.efl_mm;

% 相对峰值照度（仅有效样本）
Irel = nan(N,1);
Irel(valid) = 1 ./ rms(valid).^2;
Irel = Irel / max(Irel(valid));

% ---------- 统计 ----------
n_invalid = sum(~valid);
n_trace_error = sum(T.trace_error == 1);
n_focus_005 = sum(abs(focus) <= 0.05);
n_focus_05  = sum(abs(focus) <= 0.5);
n_focus_1   = sum(abs(focus) <= 1.0);
n_focus_2   = sum(abs(focus) <= 2.0);
n_pupil_01  = sum(abs(pupil) <= 0.1);
n_pupil_05  = sum(abs(pupil) <= 0.5);
n_pupil_1   = sum(abs(pupil) <= 1.0);

fprintf('总路径 = %d\n', N);
fprintf('RMS 无效（追迹失败）= %d；其中整条光线追迹错误 = %d\n', n_invalid, n_trace_error);
fprintf('|焦点距| <= 0.05 / 0.5 / 1 / 2 mm：%d / %d / %d / %d\n', ...
        n_focus_005, n_focus_05, n_focus_1, n_focus_2);
fprintf('|光瞳距| <= 0.1 / 0.5 / 1 mm：%d / %d / %d\n', n_pupil_01, n_pupil_05, n_pupil_1);
fprintf('RMS 中位数（有效样本）= %.4f mm，最小 = %.4f mm\n', ...
        median(rms(valid)), min(rms(valid)));

% Top 10 锐度（只排有效样本，按 1/RMS²；NaN 不参与排序）
idxv = find(valid);
[~,ov] = sort(Irel(idxv),'descend');
ord = idxv(ov(1:min(10,numel(idxv))));
fprintf('\n--- Top 10 相对峰值照度（1/RMS²，几何排序）---\n');
for k = 1:numel(ord)
    i = ord(k);
    fprintf('%2d. %-22s RMS=%8.4f mm  焦点距=%+8.4f mm  光瞳距=%+8.4f mm  I_rel=%.3e\n', ...
            k, path_name{i}, rms(i), focus(i), pupil(i), Irel(i));
end

% Top 10 光瞳鬼影（|光瞳距| 最小）
[~,ordp] = sort(abs(pupil),'ascend');
ordp = ordp(1:min(10,N));
fprintf('\n--- Top 10 光瞳鬼影（|到鬼像光瞳距离| 最小）---\n');
for k = 1:numel(ordp)
    i = ordp(k);
    fprintf('%2d. %-22s 光瞳距=%+8.4f mm  焦点距=%+9.4f mm  RMS=%8.4f mm %s\n', ...
            k, path_name{i}, pupil(i), focus(i), rms(i), ternary(valid(i),'','[RMS 无效]'));
end

% ---------- 出图 ----------
fig = figure('Color','w','Position',[30 30 1400 1080],'Visible','off');

% (a) 焦点距 vs RMS
subplot(2,1,1); hold on; box on; grid on;
semilogy(focus(valid), rms(valid), 'o', 'MarkerSize',5, ...
         'MarkerFaceColor',[0.00 0.45 0.74], 'MarkerEdgeColor','none');
semilogy(focus(~valid), rms(~valid)+1e-3*ones(sum(~valid),1), '^', 'MarkerSize',6, ...
         'MarkerEdgeColor',[0.55 0.55 0.55], 'MarkerFaceColor','none');
xline(0,'--','Color',[0.75 0.10 0.10],'LineWidth',1.2);
xline(-0.5,':','Color',[0.55 0.55 0.55],'LineWidth',1);
xline( 0.5,':','Color',[0.55 0.55 0.55],'LineWidth',1);
yline(1e-2,'-','Color',[0.85 0.33 0.10],'LineWidth',1);
set(gca,'YScale','log','FontSize',9,'LineWidth',0.8,'GridAlpha',0.15);
n_clip = sum(focus < -20 | focus > 28);
xlim([-20 28]); ylim([8e-4 1e1]);
xlabel('到鬼像焦点的距离 (mm，0 = 正好落在像面)','FontSize',10);
ylabel('鬼像 RMS 光斑半径 (mm)','FontSize',10);
title(sprintf('二次反射 1↔15 共 %d 条：焦点距 vs 锐度（%d 条 RMS 无效，空心三角）', N, n_invalid), ...
      'FontSize',10.5);
ax1 = gca; p1 = ax1.Position; ax1.Position = [p1(1) p1(2) p1(3) p1(4)-0.025];  % 给标题留边
text(-19.2, 6.0, sprintf('%d 条 |焦点距| > 20 mm 未显示（均为弱聚焦、远离像面）', n_clip), ...
     'FontSize',8, 'Color',[0.45 0.45 0.45]);
% 标注最危险三条
mark = [find(T.surf_first==15 & T.surf_second==14,1), ...
        find(T.surf_first==14 & T.surf_second==13,1), ...
        find(T.surf_first==10 & T.surf_second==8,1)];
ann  = {'15→14 像面↔窗口后 (RMS 3 µm)','14→13 窗口板双反射','10→8 L6后↔L4后'};
for k = 1:numel(mark)
    if isempty(mark(k)) || isnan(mark(k)); continue; end
    i = mark(k);
    plot(focus(i), rms(i), 'o','MarkerSize',10,'LineWidth',1.4,'Color',[0.85 0.33 0.10]);
    text(focus(i)+0.6, rms(i)*1.35, ann{k}, 'FontSize',8.5, 'Color',[0.35 0.20 0.10]);
end
legend({'RMS 有效','RMS 无效（追迹失败，纵轴置底）'}, 'Location','northeast','FontSize',8.5,'Box','off');

% (b) Top 10 相对峰值照度（对数横轴，棒棒糖图：barh 在 log 轴上不可靠）
subplot(2,2,3); hold on; box on; grid on;
ordb = flipud(ord);                 % 升序：y=1 最不危险，最危险的在最上面
yb = Irel(ordb);
base_lvl = 1e-7;
for k = 1:numel(ordb)
    semilogx([base_lvl yb(k)], [k k], '-', 'Color',[0.47 0.67 0.19], 'LineWidth',3);
    semilogx(yb(k), k, 'o', 'MarkerSize',5.5, 'MarkerFaceColor',[0.30 0.50 0.12], ...
             'MarkerEdgeColor','none');
end
lblb = arrayfun(@(k) sprintf('%s   %.1e', path_name{ordb(k)}, yb(k)), ...
                1:numel(ordb), 'UniformOutput', false);
set(gca,'XScale','log','YTick',1:numel(ordb), 'YTickLabel',lblb, 'FontSize',7.8);
xlabel('相对峰值照度 I_rel（=1/RMS²，归一化）','FontSize',9.5);
title('Top 10：鬼像有多“尖”','FontSize',10.5);
xlim([base_lvl 4]); ylim([0.4 numel(ordb)+0.6]);
set(gca,'LineWidth',0.8,'GridAlpha',0.15);

% (c) Top 10 光瞳鬼影
subplot(2,2,4); hold on; box on; grid on;
ordpp = flipud(ordp);               % 升序：最接近光瞳的一条画在最上面
yp = abs(pupil(ordpp));
barh(1:numel(ordpp), yp, 0.62, 'FaceColor',[0.30 0.55 0.80], 'EdgeColor','none');
lblp = arrayfun(@(k) sprintf('%s   %.3f mm%s', path_name{ordpp(k)}, yp(k), ...
                ternary(valid(ordpp(k)), '', '  [RMS无效]')), 1:numel(ordpp), 'UniformOutput', false);
set(gca,'YTick',1:numel(ordpp),'YTickLabel',lblp,'FontSize',7.8);
xlabel('|到鬼像光瞳的距离| (mm)','FontSize',9.5);
title('Top 10：瞳孔鬼影（越小越接近光瞳）','FontSize',10.5);
xlim([0 max(yp)*1.25]); ylim([0.4 numel(ordpp)+0.6]);
set(gca,'LineWidth',0.8,'GridAlpha',0.15);

set(findall(fig,'-property','FontName'),'FontName','Microsoft YaHei');
exportgraphics(fig, fullfile(fig_dir,'ghost_1_15_analysis.png'), 'Resolution',300);
close(fig);
fprintf('\nwrote %s\n', fullfile(fig_dir,'ghost_1_15_analysis.png'));

% ---------- 摘要文件 ----------
fid = fopen(fullfile(ana_dir,'ghost_1_15_summary.txt'),'w');
fprintf(fid,'Ghost Focus Generator 二次反射 1-15 分析摘要\n');
fprintf(fid,'数据：鬼影分析1-15.txt（2026/11/23 导出，波长 0.588 µm）\n');
fprintf(fid,'路径数 %d（C(14,2)，光阑虚面 S5 已由 Zemax 自动跳过）\n',N);
fprintf(fid,'RMS 无效 %d 条，整条追迹错误 %d 条\n',n_invalid,n_trace_error);
fprintf(fid,'|焦点距| <= 0.05/0.5/1/2 mm：%d/%d/%d/%d\n',n_focus_005,n_focus_05,n_focus_1,n_focus_2);
fprintf(fid,'|光瞳距| <= 0.1/0.5/1 mm：%d/%d/%d\n\n',n_pupil_01,n_pupil_05,n_pupil_1);
fprintf(fid,'%-6s %-24s %10s %12s %12s %12s\n','排名','路径','RMS(mm)','焦点距(mm)','光瞳距(mm)','I_rel');
for k = 1:numel(ord)
    i = ord(k);
    fprintf(fid,'%-6d %-24s %10.4f %12.4f %12.4f %12.3e\n',k,path_name{i},rms(i),focus(i),pupil(i),Irel(i));
end
fprintf(fid,'\n注：RMS=0 为追迹失败；S14 厚度 0 与 S15 重合成，14/15 起始路径为同一物理路径的重复。\n');
fclose(fid);
fprintf('wrote %s\n', fullfile(ana_dir,'ghost_1_15_summary.txt'));

function out = ternary(c,a,b)
    if c; out = a; else; out = b; end
end
