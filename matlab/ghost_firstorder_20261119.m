%% 一阶鬼影筛查 —— 6 片定心版 15 mm F/1.4 车载长焦前摄
% 方法：y–nu 近轴递推 + 双次反射路径枚举（zemax-ghost-skill 路线 B）
% 处方：车载长焦前摄15mmF1.4_定心系数-手动优化收尾.zos
% 折射率：CDGM 目录 nd（0.588 µm）
% 光瞳采样：11 条光线横跨光阑（p = 0..1），η = 不被口径拦截的比例
% 强度：I = R_i·R_j·(1-R)^N_trans·η；AR 残余 0.5%，像面按未镀膜 CMOS 窗 2%
% 弥散 D：存活光线在像面的落点跨度（真实鬼影斑直径，不是离焦估计）
% 输出：matlab/data/ghost_pairs_final.csv + layouts/no_ir_cut/ghost_firstorder.png
clear; clc; close all;

rootDir = 'D:\Zemax-mcp';
outPng  = fullfile(rootDir, 'zemax-ADAS', 'layouts', 'no_ir_cut', 'ghost_firstorder.png');
outCsv  = fullfile(rootDir, 'matlab', 'data', 'ghost_pairs_final.csv');
logFile = fullfile(rootDir, 'tmp', 'ghost_diag.txt');
if ~exist(fileparts(outCsv), 'dir'); mkdir(fileparts(outCsv)); end

logf = fopen(logFile, 'w');
lg = @(varargin) fprintf(logf, varargin{:});

% ---------------- 处方 ----------------
R = [ 30.292444786227495;  15.440361836161781;  19.594321598855050; -28.689051655560153; ...
      Inf;                  10.656502330960160; -37.872933789988410;   5.594418893802987; ...
      14.149580890275338; -13.331179488826633;  -6.521622827840516; -56.541840514082146; Inf];
nA = [1.58144; 1.00000; 1.77288; 1.00000; 1.00000; 1.77400; 1.80518; ...
      1.00000; 1.77288; 1.00000; 1.48749; 1.00000; 1.00000];
T  = [ 3.5013748687257498; 4.009718879528294; 4.691545319874674; 0.48843594697988135; ...
       0.4620509464435005; 3.8334903419576944; 2.5385774758098383; 3.320384692962178; ...
       4.21145629161534; 1.232440025221863; 1.3097885426424138; 0.900736492595912; 0];
SD = [8.0; 8.0; 7.0; 7.0; 5.206100602387041; 5.5; 5.0; 3.8; 5.5; 5.5; 5.0; 5.0; 4.6562946122908855];
lbl = {'S1','S2','S3','S4','S5','S6','S7','S8','S9','S10','S11','S12','像面'};
nB = [1; nA(1:end-1)];
c = zeros(13,1); fin = isfinite(R); c(fin) = 1 ./ R(fin);

% ---------------- 校验 ----------------
y = 1; u = 0; n = 1;
for k = 1:12
    u = u - y*c(k)*(nA(k)-n); n = nA(k);
    if k < 12, y = y + T(k)*u/n; else, y12 = y; end
end
effl = -1/u;  bfl = -y12/u;  totr = sum(T(1:12));
lg('校验 EFFL=%.4f BFL=%.4f TOTR=%.4f (Zemax 15.002 / 0.9007 / 30.500)\n', effl, bfl, totr);
assert(abs(effl-15.002) < 0.02 && abs(bfl-0.9007) < 0.01, '一阶校验未通过');

% 入瞳高度：光阑边缘
y = 1; u = 0; n = 1;
for k = 1:4
    u = u - y*c(k)*(nA(k)-n); n = nA(k);
    y = y + T(k)*u/n;
end
ypup = SD(5) / abs(y);
lg('入瞳半高 y_pup=%.4f mm\n', ypup);

% ---------------- 枚举双次反射 ----------------
optIdx = [1 2 3 4 6 7 8 9 10 11 12];
Rar = 0.005;  Rimg = 0.02;
P   = 10;                                  % 光瞳采样段数（P+1 条光线）
res = struct('i',{},'j',{},'I',{},'nt',{},'z',{},'def',{},'D',{},'y',{},'eta',{});
for a = 1:numel(optIdx)
    for b = a+1:numel(optIdx)
        res(end+1) = eval_pair(optIdx(a), optIdx(b), ypup, P, c, nA, nB, T, SD, Rar, Rimg); %#ok<SAGROW>
    end
end
for a = 1:numel(optIdx)
    res(end+1) = eval_pair(optIdx(a), 13, ypup, P, c, nA, nB, T, SD, Rar, Rimg); %#ok<SAGROW>
end

iCol = [res.i]'; jCol = [res.j]'; Irel = [res.I]'; trans = [res.nt]';
zG = [res.z]'; defoc = [res.def]'; Dmm = [res.D]'; yImg = [res.y]'; eta = [res.eta]';

peak  = Irel ./ max(Dmm, 0.02).^2;
usable = eta > 0;
offImg = abs(yImg) > SD(13) & usable;

lg('组合数 %d；eta>0 %d 个；完全被挡 %d 个；落到像面外 %d 个\n', ...
    numel(res), sum(usable), sum(eta==0), sum(offImg));
fprintf('组合 %d：有光到达 %d，全挡 %d，像面外 %d\n', ...
    numel(res), sum(usable), sum(eta==0), sum(offImg));

% ---------------- 排序 ----------------
rankMetric = peak;  rankMetric(offImg) = 0;   % 落到像面外的不计入危险度
[~, ord] = sort(rankMetric, 'descend');
fprintf('\n%-12s %9s %4s %5s %8s %9s %8s %9s %9s\n', ...
    '面组合','I_rel','Ntr','eta','z_ghost','离焦mm','弥散D','像高mm','峰值I/D2');
for r = 1:min(15, numel(ord))
    k = ord(r);
    if rankMetric(k) <= 0, break; end
    fprintf('%-12s %9.2e %4d %5.2f %8.3f %9.3f %8.3f %9.3f %9.2e\n', ...
        sprintf('%s-%s', lbl{iCol(k)}, lbl{jCol(k)}), Irel(k), trans(k), eta(k), ...
        zG(k), defoc(k), Dmm(k), yImg(k), peak(k));
end

% ---------------- CSV ----------------
fid = fopen(outCsv, 'w', 'n', 'UTF-8');
fprintf(fid, 'surface_i,surface_j,I_rel,n_trans,eta,z_ghost_mm,defocus_mm,blur_D_mm,y_img_mm,off_image,peak_per_mm2\n');
for k = 1:numel(peak)
    fprintf(fid, '%d,%d,%.4e,%d,%.3f,%.4f,%.4f,%.4f,%.4f,%d,%.4e\n', ...
        iCol(k), jCol(k), Irel(k), trans(k), eta(k), zG(k), defoc(k), Dmm(k), ...
        yImg(k), offImg(k), peak(k));
end
fclose(fid);

% ---------------- 出图 ----------------
sel = ord(rankMetric(ord) > 0);
nShow = min(12, numel(sel));
fig = figure('Visible','off','Color','w','Position',[80 80 1420 620]);
tl = tiledlayout(fig, 1, 2, 'Padding','compact','TileSpacing','compact');

ax1 = nexttile(tl); hold(ax1,'on');
scatter(ax1, Dmm(sel), peak(sel), 46, eta(sel), 'filled', 'MarkerEdgeColor','none');
set(ax1,'XScale','log','YScale','log');
xline(ax1, 0.05, 'k:', 'LineWidth', 1.2);
text(ax1, 0.052, max(peak(sel))*0.5, 'D = 0.05 mm', 'FontSize', 8, 'Color', [0.3 0.3 0.3]);
cb = colorbar(ax1); cb.Label.String = '光瞳透过率 \eta';
xlabel(ax1,'鬼影斑直径 D @像面 (mm)');
ylabel(ax1,'相对峰值照度 I/D^2  (1/mm^2)');
title(ax1,'危险度分布：左上 = 亮且小 = 最刺眼');
grid(ax1,'on'); box(ax1,'off');

ax2 = nexttile(tl);
barh(ax2, flipud(peak(sel(1:nShow))));
nm = arrayfun(@(k) sprintf('%s-%s', lbl{iCol(k)}, lbl{jCol(k)}), sel(1:nShow), 'UniformOutput', false);
set(ax2,'YTick',1:nShow,'YTickLabel',flipud(nm),'XScale','log','FontSize',9);
xlabel(ax2,'相对峰值照度 I/D^2  (1/mm^2)');
title(ax2,'危险度 Top 12 面组合');
grid(ax2,'on'); box(ax2,'off');

title(tl, sprintf('一阶鬼影筛查 · 6 片 15 mm F/1.4 · AR=%.1f%% · 有效组合 %d / %d', ...
    Rar*100, sum(usable), numel(res)), 'FontSize', 12, 'FontWeight','bold');
set(findall(fig,'-property','FontName'),'FontName','Microsoft YaHei');
set(findall(fig,'-property','FontSize'),'FontSize',9);
exportgraphics(fig, outPng, 'Resolution', 300);
close(fig);
fprintf('图: %s\n', outPng);

k1 = sel(1);
fprintf('\n最危险：%s-%s  I_rel=%.2e  eta=%.2f  离焦=%.3f mm  D=%.3f mm  像高=%.3f mm\n', ...
    lbl{iCol(k1)}, lbl{jCol(k1)}, Irel(k1), eta(k1), defoc(k1), Dmm(k1), yImg(k1));
lg('TOP: %s-%s I=%.3e eta=%.2f defoc=%.3f D=%.3f y=%.3f\n', ...
    lbl{iCol(k1)}, lbl{jCol(k1)}, Irel(k1), eta(k1), defoc(k1), Dmm(k1), yImg(k1));
fclose(logf);

% ================= 局部函数 =================
function r = eval_pair(i, j, ypup, P, c, nA, nB, T, SD, Rar, Rimg)
    ys = nan(P+1,1); us = nan(P+1,1); pass = false(P+1,1);
    for q = 0:P
        [yy, uu, blk] = trace_path(i, j, ypup*q/P, c, nA, nB, T, SD);
        if ~blk
            ys(q+1) = yy; us(q+1) = uu; pass(q+1) = true;
        end
    end
    eta = sum(pass)/(P+1);
    if eta == 0
        r = struct('i',i,'j',j,'I',0,'nt',0,'z',NaN,'def',NaN,'D',NaN,'y',NaN,'eta',0);
        return
    end
    v = ys(pass);
    D = max(v) - min(v);
    ycen = mean(v);
    % 用最外缘存活光线定义鬼影焦点
    idx = find(pass, 1, 'last');
    uu = us(idx); yy = ys(idx);
    zG = -yy/uu;  def = zG - T(12);
    nTrans = (j-1) + (j-i-1) + (12-i);
    Ri = Rar; Rj = Rar;
    if j == 13, Rj = Rimg; end
    Irel = Ri*Rj*(1-Rar)^nTrans*eta;
    r = struct('i',i,'j',j,'I',Irel,'nt',nTrans,'z',zG,'def',def,'D',D,'y',ycen,'eta',eta);
end

function [yimg, ulast, blocked] = trace_path(i, j, y0, c, nA, nB, T, SD)
    yimg = NaN; ulast = NaN; blocked = false;
    y = y0; u = 0; n = 1;
    for k = 1:j-1
        if k <= 12 && abs(y) > SD(k), blocked = true; return; end
        u = u - y*c(k)*(nA(k)-n); n = nA(k);
        y = y + T(k)*u/n;
    end
    if j <= 13 && abs(y) > SD(j), blocked = true; return; end
    u = u - y*c(j)*(-2*n); n = -n;
    for k = j-1:-1:i+1
        y = y - T(k)*u/n;
        if abs(y) > SD(k), blocked = true; return; end
        nn = -nB(k);
        u = u - y*c(k)*(nn-n); n = nn;
    end
    y = y - T(i)*u/n;
    if abs(y) > SD(i), blocked = true; return; end
    u = u - y*c(i)*(-2*n); n = -n;
    for k = i+1:12
        y = y + T(k-1)*u/n;
        if abs(y) > SD(k), blocked = true; return; end
        u = u - y*c(k)*(nA(k)-n); n = nA(k);
    end
    yimg = y + T(12)*u;
    ulast = u;
end
