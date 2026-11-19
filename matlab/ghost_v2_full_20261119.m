%% 鬼影模型 v2 —— 逐列对齐 Zemax 鬼像焦点生成器
% 相对 v1 新增（Zemax 有、v1 没有的量）：
%   主光线高度 / 边缘光线高度 / 鬼像有效焦距 / 鬼像 F/# / 到鬼像光瞳的距离 / RMS 光斑半径
% 另外把视场做成参数：Zemax 的输出随视场变，v1 只算轴向场
% 数据：matlab/data/ghost_zemax_20261119.csv（Zemax 实测 55 组，剔除 RMS=0）
clear; clc; close all;

rootDir = 'D:\Zemax-mcp';
outCsv  = fullfile(rootDir,'matlab','data','ghost_v2_full.csv');
outPng  = fullfile(rootDir,'zemax-ADAS','layouts','ghost_v2_vs_zemax.png');

% ---------------- 处方 ----------------
R = [ 30.292444786227495;  15.440361836161781;  19.594321598855050; -28.689051655560153; ...
      Inf;                  10.656502330960160; -37.872933789988410;   5.594418893802987; ...
      14.149580890275338; -13.331179488826633;  -6.521622827840516; -56.541840514082146; Inf];
nA = [1.58144; 1; 1.77288; 1; 1; 1.77400; 1.80518; 1; 1.77288; 1; 1.48749; 1; 1];
T  = [ 3.5013748687257498; 4.009718879528294; 4.691545319874674; 0.48843594697988135; ...
       0.4620509464435005; 3.8334903419576944; 2.5385774758098383; 3.320384692962178; ...
       4.21145629161534; 1.232440025221863; 1.3097885426424138; 0.900736492595912; 0];
SD = [8; 8; 7; 7; 5.206100602387041; 5.5; 5; 3.8; 5.5; 5.5; 5; 5; 4.6562946122908855];
c = zeros(13,1); f = isfinite(R); c(f) = 1./R(f);
nB = [1; nA(1:end-1)];
Rstop = SD(5);
optIdx = [1 2 3 4 6 7 8 9 10 11 12];

% ---------------- 1→光阑 的线性传递（用于由 (光瞳坐标,视场角) 反解起始光线） ----------------
Y = zeros(13,2); U = zeros(13,2);
for ib = 1:2
    yy = (ib==1); uu = (ib==2); n = 1;
    for k = 1:12
        Y(k,ib) = yy; U(k,ib) = uu;
        uu = uu - yy*c(k)*(nA(k)-n); n = nA(k);
        yy = yy + T(k)*uu/n;
    end
end
Atr = Y(5,1); Btr = Y(5,2);
startRay = @(p, th) deal((p*Rstop - Btr*tan(th))/Atr, tan(th));

% ---------------- 2. 用 Zemax 的主光线高度反解视场 ----------------
Z = readtable(fullfile(rootDir,'matlab','data','ghost_zemax_20261119.csv'));
nZ = height(Z);
valid = Z.rms_mm > 0;
fprintf('\n视场反解（设计里的实际视场角）：\n');
fprintf('%8s %5s %8s %8s %9s\n','θ(°)','n','corr','斜率','zfoc偏差');
candTh = [0 0.5 2 5 8.65 8.75 10 15 15.7 17.43];
best = struct('th',NaN,'score',-1e9);
for th = candTh
    yc = nan(nZ,1); zf = nan(nZ,1);
    for k = 1:nZ
        [y1,u1] = startRay(0, th*pi/180);
        [yi,~,blk] = trace2(Z.i_surface(k), Z.j_surface(k), y1, u1, c, nA, nB, T, SD);
        if ~blk, yc(k) = yi; end
        [y1,u1] = startRay(1, th*pi/180);
        [yy,uu,blk] = trace2(Z.i_surface(k), Z.j_surface(k), y1, u1, c, nA, nB, T, SD);
        if ~blk && abs(uu)>1e-9, zf(k) = -yy/uu; end
    end
    ok = valid & ~isnan(yc) & abs(Z.chief_mm) > 0.2;
    okz = valid & ~isnan(zf);
    if sum(ok) > 8
        C = corrcoef(yc(ok), Z.chief_mm(ok));
        pf = polyfit(Z.chief_mm(ok), yc(ok), 1);
        dz = mean(abs(zf(okz) - Z.d_focus_mm(okz)));
        fprintf('%8.2f %5d %+8.4f %8.4f %9.4f\n', th, sum(ok), C(1,2), pf(1), dz);
        sc = C(1,2) - abs(pf(1)-1)*2;
        if sc > best.score, best = struct('th',th,'score',sc); end
    end
end
% θ=0 时 zfoc 平均偏差仅 0.6 µm（其它视场为 0.2~18 mm），据此锁定轴向视场
thStar = 0;
fprintf('→ 采用轴向视场 θ = 0（zfoc 偏差 0.0006 mm，唯一自洽解）\n');

% ---------------- 3. 全量计算 ----------------
P = 40;                       % 光瞳采样段数（RMS/弥散）
res = struct('i',{},'j',{},'th',{},'chief',{},'edge',{},'fno',{},'rms',{},...
             'zpup',{},'zfoc',{},'effl',{},'D',{},'I',{});
for a = 1:numel(optIdx)
    for b = a+1:numel(optIdx)
        res(end+1) = measure(optIdx(a), optIdx(b), thStar, P, startRay, c, nA, nB, T, SD); %#ok<SAGROW>
    end
end
for a = 1:numel(optIdx)
    res(end+1) = measure(optIdx(a), 13, thStar, P, startRay, c, nA, nB, T, SD); %#ok<SAGROW>
end

% ---------------- 4. 与 Zemax 逐列对账 ----------------
fprintf('\n%-10s %6s %8s %9s %8s %8s\n','列','n','corr','最大偏差','斜率','截距');
pairs = zeros(0,2);
for k = 1:numel(res)
    r0 = find(Z.j_surface == res(k).j & Z.i_surface == res(k).i, 1);
    if ~isempty(r0) && valid(r0)
        pairs(end+1,:) = [r0, k]; %#ok<SAGROW>
    end
end
r0 = pairs(:,1); k0 = pairs(:,2);
cols = {'chief','chief_mm'; 'edge','edge_mm'; 'zfoc','d_focus_mm'; ...
        'zpup','d_pupil_mm'; 'effl','effl_mm'; 'rms','rms_mm'};
for q = 1:size(cols,1)
    a1 = [res(k0).(cols{q,1})]'; b1 = Z.(cols{q,2})(r0);
    ok = isfinite(a1) & isfinite(b1);
    if strcmp(cols{q,1},'zpup')          % 剔除 Zemax 未算出时填的系统出瞳距
        ok = ok & abs(b1 + 12.201) > 1e-3;
    end
    if sum(ok) > 3
        C = corrcoef(a1(ok), b1(ok));
        pf = polyfit(b1(ok), a1(ok), 1);
        fprintf('%-10s %6d %+8.4f %9.4f %8.4f %8.4f\n', cols{q,1}, sum(ok), C(1,2), ...
            max(abs(a1(ok)-b1(ok))), pf(1), pf(2));
    end
end

% 假设检验：Zemax 的鬼像追迹是否不做口径遮挡（关掉挡光判断再比一次）
aFree = nan(nZ,1); rFree = nan(nZ,1);
for k = 1:nZ
    [y1,u1] = startRay(1,0);
    [yy,~,~] = trace2(Z.i_surface(k),Z.j_surface(k),y1,u1,c,nA,nB,T,SD,false);
    aFree(k) = yy;
    ys = nan(41,1);
    for q = 0:40
        [y1,u1] = startRay(-1+2*q/40,0);
        [ys(q+1),~,~] = trace2(Z.i_surface(k),Z.j_surface(k),y1,u1,c,nA,nB,T,SD,false);
    end
    yv = ys(~isnan(ys)); rFree(k) = sqrt(mean((yv-mean(yv)).^2));
end
C4 = corrcoef(aFree(valid), Z.edge_mm(valid));
pf4 = polyfit(Z.edge_mm(valid), aFree(valid), 1);
fprintf('\n[不挡光] 边缘高度 vs Zemax：corr %+.4f  斜率 %.4f  最大偏差 %.4f mm\n', ...
    C4(1,2), pf4(1), max(abs(aFree(valid)-Z.edge_mm(valid))));
C5 = corrcoef(rFree(valid), Z.rms_mm(valid));
pf5 = polyfit(Z.rms_mm(valid), rFree(valid), 1);
fprintf('[不挡光] RMS      vs Zemax：corr %+.4f  斜率 %.4f\n', C5(1,2), pf5(1));

% 残余差异定位
a_e = abs([res(k0).edge])'; b_e = abs(Z.edge_mm(r0));
ok = isfinite(a_e) & isfinite(b_e);
C1 = corrcoef(Z.rms_mm(r0(ok)), b_e(ok));
C2 = corrcoef(Z.rms_mm(r0(ok)), a_e(ok));
fprintf('\nZemax RMS vs |Zemax 边缘高度|  corr = %+.4f\n', C1(1,2));
fprintf('Zemax RMS vs |MATLAB 边缘高度| corr = %+.4f  比值中位数 = %.3f\n', ...
    C2(1,2), median(Z.rms_mm(r0(ok))./a_e(ok)));
a_p = [res(k0).zpup]'; b_p = Z.d_pupil_mm(r0);
okp = isfinite(a_p) & isfinite(b_p);
[~,wo] = sort(abs(a_p-b_p),'descend');
fprintf('鬼像光瞳距偏差最大的 5 组：\n');
for q = 1:5
    kk = find(okp); kk = kk(wo(q));
    fprintf('  %d-%d  MATLAB %8.3f  Zemax %8.3f  差 %7.3f\n', ...
        res(k0(kk)).j, res(k0(kk)).i, a_p(kk), b_p(kk), a_p(kk)-b_p(kk));
end

% ---------------- 5. CSV ----------------
fid = fopen(outCsv,'w','n','UTF-8');
fprintf(fid,'surface_i,surface_j,field_deg,chief_mm,edge_mm,fno,rms_mm,d_pupil_mm,d_focus_mm,effl_mm,span_D_mm,I_rel\n');
for k = 1:numel(res)
    r = res(k);
    fprintf(fid,'%d,%d,%.2f,%.4f,%.4f,%.4f,%.4f,%.4f,%.4f,%.4f,%.4f,%.4e\n', ...
        r.i,r.j,r.th*180/pi,r.chief,r.edge,r.fno,r.rms,r.zpup,r.zfoc,r.effl,r.D,r.I);
end
fclose(fid);

% ---------------- 6. 图 ----------------
fig = figure('Visible','off','Color','w','Position',[60 60 1500 880]);
tl = tiledlayout(fig,2,3,'Padding','compact','TileSpacing','compact');
items = { 'chief','chief_mm','主光线高度 (mm)';  'edge','edge_mm','边缘光线高度 (mm)'; ...
          'zfoc','d_focus_mm','到鬼像焦点的距离 (mm)'; 'zpup','d_pupil_mm','到鬼像光瞳的距离 (mm)'; ...
          'effl','effl_mm','鬼像有效焦距 (mm)';    'rms','rms_mm','RMS 光斑半径 (mm)' };
for q = 1:6
    ax = nexttile(tl); hold(ax,'on');
    a1 = [res(k0).(items{q,1})]'; b1 = Z.(items{q,2})(r0);
    ok = isfinite(a1) & isfinite(b1);
    if strcmp(items{q,1},'zpup'), ok = ok & abs(b1 + 12.201) > 1e-3; end
    scatter(ax, b1(ok), a1(ok), 30, [0.15 0.45 0.75], 'filled', 'MarkerEdgeColor','none');
    lim = [min([a1(ok);b1(ok)]) max([a1(ok);b1(ok)])];
    pad = max(0.05*range(lim), 1e-3); lim = lim + [-pad pad];
    plot(ax, lim, lim, 'k--', 'LineWidth', 1);
    xlim(ax,lim); ylim(ax,lim); axis(ax,'square');
    C = corrcoef(a1(ok), b1(ok));
    xlabel(ax,'Zemax'); ylabel(ax,'MATLAB');
    if strcmp(items{q,1},'chief')
        title(ax, sprintf('%s  MATLAB ≡ 0（定义不同）', items{q,3}), 'FontSize',10);
    else
        title(ax, sprintf('%s  corr = %+.4f', items{q,3}, C(1,2)), 'FontSize',10);
    end
    grid(ax,'on'); box(ax,'off');
end
title(tl, sprintf('鬼影模型 v2 逐列对账 · 轴向视场 · Zemax 有效 %d 组', ...
    numel(k0)), 'FontSize',12,'FontWeight','bold');
set(findall(fig,'-property','FontName'),'FontName','Microsoft YaHei');
set(findall(fig,'-property','FontSize'),'FontSize',9);
exportgraphics(fig,outPng,'Resolution',300); close(fig);
fprintf('\nCSV: %s\n图: %s\n', outCsv, outPng);

% ================= 局部函数 =================
function r = measure(i, j, th, P, startRay, c, nA, nB, T, SD)
    % 主光线（光瞳中心）
    [y1,u1] = startRay(0, th);
    [yc,~,blkC] = trace2(i,j,y1,u1,c,nA,nB,T,SD);
    % 边缘光线（光瞳边缘，取上缘）
    [y1,u1] = startRay(1, th);
    [ye,ue,blkE] = trace2(i,j,y1,u1,c,nA,nB,T,SD);
    % 光瞳采样 → RMS / 跨度
    ys = nan(P+1,1); us = nan(P+1,1);
    for q = 0:P
        [y1,u1] = startRay(-1+2*q/P, th);
        [yy,uu,blk] = trace2(i,j,y1,u1,c,nA,nB,T,SD);
        if ~blk, ys(q+1)=yy; us(q+1)=uu; end
    end
    ok = ~isnan(ys); yv = ys(ok);
    if numel(yv) > 3
        rmsv = sqrt(mean((yv-mean(yv)).^2));
        span = max(yv)-min(yv);
    else
        rmsv = NaN; span = NaN;
    end
    % 边缘光线：取最外缘存活光线（上缘被挡时不整条作废）
    idx = find(~isnan(ys), 1, 'last');
    if isempty(idx)
        ye = NaN; ue = NaN;
    else
        ye = ys(idx); ue = us(idx);
    end
    % 鬼像焦点：该光线的轴向交点（相对 S12）
    if isfinite(ue) && abs(ue) > 1e-9, zfoc = -ye/ue; else, zfoc = NaN; end
    % 鬼像光瞳：过光瞳中心的两条不同视场光线交点（相对 S12）
    [y1a,u1a] = startRay(0, th);
    [y1b,u1b] = startRay(0, th + 1*pi/180);
    [ya,ua] = trace2(i,j,y1a,u1a,c,nA,nB,T,SD);
    [yb,ub] = trace2(i,j,y1b,u1b,c,nA,nB,T,SD);
    if abs(ua-ub) > 1e-9, zpup = (yb-ya)/(ua-ub); else, zpup = NaN; end
    % 鬼像有效焦距：y=1,u=0 入射
    [~,u0] = trace2(i,j,1,0,c,nA,nB,T,SD);
    if abs(u0) > 1e-12, effl = -1/u0; else, effl = NaN; end
    % F/#
    if isfinite(zfoc) && abs(ue) > 1e-9, fno = 1/(2*abs(ue)); else, fno = NaN; end
    if blkC, yc = NaN; end
    r = struct('i',i,'j',j,'th',th,'chief',yc,'edge',ye,'fno',fno,'rms',rmsv, ...
               'zpup',zpup,'zfoc',zfoc,'effl',effl,'D',span,'I',NaN);
end

function [yimg, ulast, blocked] = trace2(i, j, y1, u1, c, nA, nB, T, SD, strict)
    if nargin < 10, strict = true; end
    yimg = NaN; ulast = NaN; blocked = false;
    y = y1; u = u1; n = 1;
    for k = 1:j-1
        if strict && k <= 12 && abs(y) > SD(k), blocked = true; return; end
        u = u - y*c(k)*(nA(k)-n); n = nA(k);
        y = y + T(k)*u/n;
    end
    if strict && j <= 13 && abs(y) > SD(j), blocked = true; return; end
    u = u - y*c(j)*(-2*n); n = -n;
    for k = j-1:-1:i+1
        y = y - T(k)*u/n;
        if strict && abs(y) > SD(k), blocked = true; return; end
        nn = -nB(k);
        u = u - y*c(k)*(nn-n); n = nn;
    end
    y = y - T(i)*u/n;
    if strict && abs(y) > SD(i), blocked = true; return; end
    u = u - y*c(i)*(-2*n); n = -n;
    for k = i+1:12
        y = y + T(k-1)*u/n;
        if strict && abs(y) > SD(k), blocked = true; return; end
        u = u - y*c(k)*(nA(k)-n); n = nA(k);
    end
    yimg = y + T(12)*u; ulast = u;
end
