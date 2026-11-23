%% 一阶鬼影筛查（MATLAB 独立计算）—— 长后焦 v8 R11 交付版
% 方法：y–nu 近轴递推 + 双次反射路径枚举（zemax-ghost-skill 路线 B）
% 与 Zemax Ghost Focus Generator 的区别：
%   Zemax 只给几何（焦点距/光瞳距/RMS），不含口径拦截与强度；
%   本脚本自己追迹 11 条光瞳光线、逐面查半口径，给出
%   光瞳透过率 eta、存活光线在像面的弥散 D、强度 I = Ri·Rj·(1-R)^N·eta，
%   再按峰值照度 I/D² 排序 —— 这一列 Zemax 那份文件里没有。
% 然后与 Zemax 的 91 条"到鬼像焦点的距离"做逐项交叉校验。
%
% 处方：长后焦_v8_Z115_SDopt10_R11_20261122.zos（0.588 µm，nd 取自 CDGM.AGF）
% 输出：data/ghost_firstorder_R11.csv、figs/ghost_firstorder_R11.png、
%       analysis/ghost_firstorder_R11.txt

clear; clc; close all;

base    = fileparts(mfilename('fullpath'));
if isempty(base); base = pwd; end
outCsv  = fullfile(base,'data','ghost_firstorder_R11.csv');
outPng  = fullfile(base,'figs','ghost_firstorder_R11.png');
outLog  = fullfile(base,'analysis','ghost_firstorder_R11.txt');
if ~exist(fullfile(base,'data'),'dir'); mkdir(fullfile(base,'data')); end
if ~exist(fullfile(base,'figs'),'dir'); mkdir(fullfile(base,'figs')); end
if ~exist(fullfile(base,'analysis'),'dir'); mkdir(fullfile(base,'analysis')); end
logf = fopen(outLog,'w');

% ---------------- 处方（面 1–14 + 像面 15） ----------------
NS = 15;  NR = 14;                     % 像面号 / 折射面数
R = [ 34.6149; 17.5416; 23.2843; -25.1589;  Inf; 10.7865; -26.3832; 5.6226; ...
      15.5450; -12.5018; -7.1000; Inf; Inf; Inf; Inf];
T = [ 3.5436; 4.2272; 3.6362; 0.5000; 0.5000; 3.9431; 2.3959; 3.8327; ...
      3.5893; 0.9418; 1.4320; 1.0000; 0.4000; 0.0000; 0];
nA = [1.517420; 1.00000; 1.755000; 1.00000; 1.00000; 1.804000; 1.805190; 1.00000; ...
      1.804000; 1.00000; 1.487490; 1.00000; 1.516800; 1.00000; 1.00000];
SD = [8.000; 8.000; 6.500; 6.500; 5.306; 5.360; 5.360; 3.870; ...
      5.300; 5.300; 5.000; 5.000; 4.698; 4.668; 4.668];
lbl = {'S1','S2','S3','S4','S5光阑','S6','S7','S8','S9','S10','S11','S12','S13窗','S14窗','S15像面'};
nB  = [1; nA(1:end-1)];
c = zeros(NS,1); fin = isfinite(R); c(fin) = 1./R(fin);

% ---------------- 一阶校验 ----------------
y = 1; u = 0; n = 1;
for k = 1:NR
    u = u - y*c(k)*(nA(k)-n); n = nA(k);
    y = y + T(k)*u/n;
end
effl = -1/u;  yImgPar = y;  totr = sum(T(1:NR));
fprintf(logf,'校验：EFFL=%.4f (Zemax 15.0372)  TOTR=%.4f (Zemax 29.9417)  像面处 y=%.5f\n', ...
        effl, totr, yImgPar);
fprintf('校验：EFFL=%.4f  TOTR=%.4f  像面 y=%.5f\n', effl, totr, yImgPar);
assert(abs(effl-15.0372) < 0.05, 'EFFL 校验未通过：检查 nd 或面表');
assert(abs(totr-29.9417) < 1e-3, 'TOTR 校验未通过');

% 入瞳半高（光阑 S5 边缘对应的物方高度）
y = 1; u = 0; n = 1;
for k = 1:4
    u = u - y*c(k)*(nA(k)-n); n = nA(k);
    y = y + T(k)*u/n;
end
ypup = SD(5)/abs(y);
fprintf(logf,'入瞳半高 y_pup=%.4f mm（EPD/2=5.3705）\n\n', ypup);

% ---------------- 枚举双次反射 ----------------
optIdx = [1 2 3 4 6 7 8 9 10 11 12 13 14 15];   % 跳过光阑虚面 S5
Rar = 0.005;  Rimg = 0.02;  P = 10;
res = struct('i',{},'j',{},'I',{},'nt',{},'z',{},'def',{},'D',{},'y',{},'eta',{});
for a = 1:numel(optIdx)
    for b = a+1:numel(optIdx)
        res(end+1) = eval_pair(optIdx(a),optIdx(b),ypup,P,c,nA,nB,T,SD,NS,NR,Rar,Rimg); %#ok<SAGROW>
    end
end

iCol=[res.i]'; jCol=[res.j]'; Irel=[res.I]'; trans=[res.nt]';
zG=[res.z]'; defoc=[res.def]'; Dmm=[res.D]'; yImg=[res.y]'; eta=[res.eta]';
peak = Irel ./ max(Dmm,0.02).^2;
% 路径命名按物理顺序：先反射 j（靠近像方），再反射 i（靠近物方）
pname = @(k) sprintf('%s→%s', lbl{jCol(k)}, lbl{iCol(k)});
usable = eta > 0;
offImg = abs(yImg) > SD(NS) & usable;
fprintf('组合 %d；有光到达 %d；全被挡 %d；落像面外 %d\n', numel(res), sum(usable), sum(eta==0), sum(offImg));
fprintf(logf,'组合 %d；有光到达 %d；全被挡 %d；落像面外 %d\n\n', numel(res), sum(usable), sum(eta==0), sum(offImg));

rankMetric = peak;  rankMetric(offImg) = 0;
[~, ord] = sort(rankMetric,'descend');
fprintf(logf,'%-16s %10s %5s %5s %10s %9s %8s %9s %10s\n', ...
        '路径(先→后)','I_rel','Ntr','eta','z_ghost','离焦mm','弥散D','像高mm','峰值I/D2');
for r = 1:min(15,numel(ord))
    k = ord(r);
    if rankMetric(k) <= 0; break; end
    fprintf(logf,'%-16s %10.2e %5d %5.2f %10.3f %9.3f %8.3f %9.3f %10.2e\n', ...
        pname(k), Irel(k), trans(k), eta(k), ...
        zG(k), defoc(k), Dmm(k), yImg(k), peak(k));
end
fprintf(logf,'\n注：路径按「第一次反射→第二次反射」书写；I_rel 已按 GISET 口径乘好反射率与光瞳通过率，\n');
fprintf(logf,'    对落回同一像元的回反射路径（弥散 D→0），GISET ≈ I_rel 本身。\n\n');

fid = fopen(outCsv,'w','n','UTF-8');
fprintf(fid,'surf_first,surf_second,I_rel,n_trans,eta,z_ghost_mm,defocus_mm,blur_D_mm,y_img_mm,off_image,peak_per_mm2\n');
for k = 1:numel(peak)
    fprintf(fid,'%d,%d,%.4e,%d,%.3f,%.4f,%.4f,%.4f,%.4f,%d,%.4e\n', ...
        jCol(k),iCol(k),Irel(k),trans(k),eta(k),zG(k),defoc(k),Dmm(k),yImg(k),offImg(k),peak(k));
end
fclose(fid);

% ---------------- 与 Zemax Ghost Focus Generator 交叉校验 ----------------
Z = readtable(fullfile(base,'data','ghost_1_15_bounce.csv'));
nMatch = 0; dM = []; dZ = []; rM = []; rZ = [];
for k = 1:height(Z)
    a = Z.surf_first(k); b = Z.surf_second(k);          % Zemax: 先反射 a，再反射 b
    idx = find(iCol==b & jCol==a, 1);                    % MATLAB: i=b (后反射)，j=a
    if isempty(idx) || ~isfinite(defoc(idx)); continue; end
    nMatch = nMatch+1;
    dM(end+1,1) = defoc(idx);  %#ok<SAGROW>
    dZ(end+1,1) = Z.focus_dist_mm(k); %#ok<SAGROW>
    rM(end+1,1) = Dmm(idx)/2;  %#ok<SAGROW>
    rZ(end+1,1) = Z.rms_radius_mm(k); %#ok<SAGROW>
end
cc = corrcoef(dM,dZ);  corr_focus = cc(1,2);
mad = median(abs(dM-dZ));
sel = rZ > 0;  cc2 = corrcoef(rM(sel), rZ(sel));  corr_rms = cc2(1,2);
fprintf('交叉校验：可比 %d 条；焦点距 corr=%.4f，中位偏差=%.4f mm；RMS vs D/2 corr=%.3f\n', ...
        nMatch, corr_focus, mad, corr_rms);
fprintf(logf,'\n交叉校验：可比 %d 条；焦点距 corr=%.4f，中位偏差=%.4f mm；RMS vs D/2 corr=%.3f\n', ...
        nMatch, corr_focus, mad, corr_rms);

% ---------------- 出图 ----------------
sel2 = ord(rankMetric(ord) > 0);  nShow = min(12,numel(sel2));
fig = figure('Visible','off','Color','w','Position',[60 60 1450 700]);
tl = tiledlayout(fig,1,2,'Padding','compact','TileSpacing','compact');

ax1 = nexttile(tl); hold(ax1,'on');
scatter(ax1, Dmm(sel2), peak(sel2), 46, eta(sel2), 'filled','MarkerEdgeColor','none');
set(ax1,'XScale','log','YScale','log');
xline(ax1,0.05,'k:','LineWidth',1.2);
text(ax1,0.052,max(peak(sel2))*0.5,'D = 0.05 mm','FontSize',8,'Color',[0.3 0.3 0.3]);
cb = colorbar(ax1); cb.Label.String = '光瞳透过率 \eta';
xlabel(ax1,'鬼影斑直径 D @像面 (mm)'); ylabel(ax1,'相对峰值照度 I/D^2 (1/mm^2)');
title(ax1,'MATLAB 独立计算：左上 = 亮且小 = 最刺眼');
grid(ax1,'on'); box(ax1,'off');

ax2 = nexttile(tl);
barh(ax2, flipud(peak(sel2(1:nShow))));
nm = arrayfun(@(k) pname(k), sel2(1:nShow),'UniformOutput',false);
set(ax2,'YTick',1:nShow,'YTickLabel',flipud(nm),'XScale','log','FontSize',8.5);
xlabel(ax2,'相对峰值照度 I/D^2 (1/mm^2)');
title(ax2,sprintf('危险度 Top %d（AR=%.1f%%，像面 = 2%%）',nShow,Rar*100));
grid(ax2,'on'); box(ax2,'off');

title(tl, sprintf('一阶鬼影筛查 · v8 R11 · 有效组合 %d / %d · 与 Zemax 焦点距 corr=%.3f', ...
      sum(usable), numel(res), corr_focus), 'FontSize',12,'FontWeight','bold');
set(findall(fig,'-property','FontName'),'FontName','Microsoft YaHei');
exportgraphics(fig,outPng,'Resolution',300);
close(fig);
fprintf('图：%s\n', outPng);

if ~isempty(sel2)
    k1 = sel2(1);
    fprintf('\n最危险：%s  eta=%.2f  离焦=%.3f mm  D=%.4f mm  峰值=%.2e  GISET≈%.2e\n', ...
        pname(k1),eta(k1),defoc(k1),Dmm(k1),peak(k1),Irel(k1));
    fprintf(logf,'\n最危险：%s  eta=%.2f  离焦=%.3f mm  D=%.4f mm  峰值=%.2e  GISET≈%.2e\n', ...
        pname(k1),eta(k1),defoc(k1),Dmm(k1),peak(k1),Irel(k1));

    % ---------- 镀膜敏感性：支配路径的 GISET 完全由两个反射率决定 ----------
    nTk = trans(k1);  etk = eta(k1);
    Rsens = [0.02 0.05 0.10 0.20];      % sensor 有效反射率
    Rars  = [0.002 0.005 0.010 0.020];  % 窗口后表面 AR 残余反射率
    G = Rsens' * Rars .* (1-Rars).^nTk * etk;   % 行 = R_sensor，列 = R_AR
    fprintf(logf,'\n镀膜敏感性：GISET(%s) = R_sensor × R_AR × (1-R_AR)^%d × eta(%.2f)\n', ...
            pname(k1), nTk, etk);
    fprintf(logf,'%12s','R_sensor \ R_AR');
    fprintf(logf,'%11.1f%%', Rars*100);  fprintf(logf,'\n');
    for a = 1:numel(Rsens)
        fprintf(logf,'%11.0f%%', Rsens(a)*100);
        fprintf(logf,'%11.2e', G(a,:));  fprintf(logf,'\n');
    end
    fprintf(logf,'判据（车载）：<1e-3 可接受；1e-3~1e-2 强光源下可见；>1e-2 必须整改。\n');
    fprintf('镀膜敏感性矩阵已写入日志（GISET %s = R_sensor×R_AR×(1-R_AR)^%d×eta）\n', pname(k1), nTk);

    fid2 = fopen(fullfile(base,'data','ghost_giset_sensitivity_R11.csv'),'w','n','UTF-8');
    fprintf(fid2,'R_sensor,R_AR,GISET\n');
    for a = 1:numel(Rsens)
        for b = 1:numel(Rars)
            fprintf(fid2,'%.3f,%.4f,%.4e\n', Rsens(a), Rars(b), G(a,b));
        end
    end
    fclose(fid2);
end
fclose(logf);
fprintf('日志：%s\n', outLog);

% ================= 局部函数 =================
function r = eval_pair(i,j,ypup,P,c,nA,nB,T,SD,NS,NR,Rar,Rimg)
    ys = nan(P+1,1); us = nan(P+1,1); pass = false(P+1,1);
    for q = 0:P
        [yy,uu,blk] = trace_path(i,j,ypup*q/P,c,nA,nB,T,SD,NR);
        if ~blk; ys(q+1)=yy; us(q+1)=uu; pass(q+1)=true; end
    end
    eta = sum(pass)/(P+1);
    if eta == 0
        r = struct('i',i,'j',j,'I',0,'nt',0,'z',NaN,'def',NaN,'D',NaN,'y',NaN,'eta',0); return;
    end
    v = ys(pass);  D = max(v)-min(v);  ycen = mean(v);
    idx = find(pass,1,'last');  zG = -ys(idx)/us(idx);  def = zG - T(NR);
    nTrans = (j-1)+(j-i-1)+(NR-i);
    Ri = Rar;  Rj = Rar;  if j == NS, Rj = Rimg; end
    Irel = Ri*Rj*(1-Rar)^nTrans*eta;
    r = struct('i',i,'j',j,'I',Irel,'nt',nTrans,'z',zG,'def',def,'D',D,'y',ycen,'eta',eta);
end

function [yimg,uLast,blocked] = trace_path(i,j,y0,c,nA,nB,T,SD,NR)
    yimg = NaN; uLast = NaN; blocked = false;
    y = y0; u = 0; n = 1;
    for k = 1:j-1
        if k <= NR && abs(y) > SD(k); blocked = true; return; end
        u = u - y*c(k)*(nA(k)-n); n = nA(k);
        y = y + T(k)*u/n;
    end
    if abs(y) > SD(j); blocked = true; return; end
    u = u - y*c(j)*(-2*n); n = -n;                 % 第一次反射（面 j）
    for k = j-1:-1:i+1
        y = y - T(k)*u/n;
        if abs(y) > SD(k); blocked = true; return; end
        nn = -nB(k);  u = u - y*c(k)*(nn-n);  n = nn;
    end
    y = y - T(i)*u/n;
    if abs(y) > SD(i); blocked = true; return; end
    u = u - y*c(i)*(-2*n); n = -n;                 % 第二次反射（面 i）
    for k = i+1:NR
        y = y + T(k-1)*u/n;
        if abs(y) > SD(k); blocked = true; return; end
        u = u - y*c(k)*(nA(k)-n); n = nA(k);
    end
    yimg = y + T(NR)*u;  uLast = u;
end
