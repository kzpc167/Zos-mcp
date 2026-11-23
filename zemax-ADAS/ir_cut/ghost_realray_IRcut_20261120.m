function ghost_realray_IRcut_20261120()
%% 鬼影实光线模型（IR-CUT 版）—— 二维子午面 + 非球面 + 矢量 Snell
% 目的：回答「鬼影光斑会不会随视场扫出传感器」，补 §6.7 的离轴缺口
% 旋转对称 ⇒ 任一方位场点等价于"坐标轴转到该方向的子午面"，二维追迹是精确的
% 数据：Zemax GUI 导出 zemax-ADAS/加窗口鬼影分析1-15.txt（91 组）作轴向对账
% 输出：zemax-ADAS/ir_cut/data/ghost_realray_IRcut.csv + ir_cut/figs/ghost_realray_fields_IRcut.png
clc; close all;
rootDir = fileparts(fileparts(mfilename('fullpath')));

%% ---------------- 处方（15 面：S1–S14 + 像面 S15）----------------
R  = [ 34.78036051606992; 17.435718549658848; 20.530294107490068; -28.595593345652322; ...
       Inf; 10.352808109044268; -38.17719639780744; 5.624211470379923; ...
       14.034021134058413; -12.052375463335132; -6.407646360638522; Inf; Inf; Inf; Inf];
kk = [-1;0;0;0;0;0;0;0;0;0;-1;0;0;0;0];
A4 = [-6.5e-05;0;0;0;0;0;0;0;0;0; 6.299414294933923e-04;0;0;0;0];
A6 = [-1.854e-07;0;0;0;0;0;0;0;0;0; 2.3728239639343362e-07;0;0;0;0];
T  = [ 3.307824716548504; 4.0; 4.0797171225286855; 0.47; 0.49; ...
       4.073732764136589; 2.039046734811184; 3.8; 4.288669457140633; 1.0; ...
       1.3510440336689604; 0.7; 0.4; 0.0; 0];
nA = [1.58144;1;1.77288;1;1;1.77400;1.80518;1;1.77288;1;1.48749;1;1.5168;1;1];
SD = [8;8;7;7;5.26;5.5;5;3.8;5.5;5.5;5;5;6;6;4.6504];

NS = 15;  NOPT = 14;                       % 最后一面 S14；像面 S15（与 S14 重合）
c  = zeros(NS,1); mskR = isfinite(R); c(mskR) = 1./R(mskR);
Z  = cumsum([0; T(1:NOPT)]);
Rstop = SD(5);

HALF_W = 4.04; HALF_H = 2.29;              % 8.08 × 4.58 mm 传感器（半宽）
% 视场按传感器矩形定：四角 = (4.04, 2.29) → 17.19° @ 29.5°方位
FIELDS = [0 0; 8.68 90; 15.07 0; 17.19 29.5];
optIdx = [1 2 3 4 6 7 8 9 10 11 12 13 14]; % 剔除光阑 S5
PN = 20;

%% ---- 自检 ----
[yN, uN] = traceForward(1, 0);
uAng = atan(uN);
fprintf('自检：边缘光线像高 %.4f mm，像方角 %.2f°，对应 F/%.2f\n', ...
    yN, abs(uAng)*180/pi, 1/(2*abs(tan(uAng))));

%% ---- 视场角标定：让主光线正好打到传感器矩形边上 ----
% 否则「鬼影中心是否落在传感器内」判的是视场定义误差，不是鬼影本身
for ff = 2:size(FIELDS,1)
    az  = FIELDS(ff,2)*pi/180;
    tgt = min(HALF_W/max(abs(cos(az)),1e-12), HALF_H/max(abs(sin(az)),1e-12));
    th  = FIELDS(ff,1);
    for it = 1:5
        yc = traceForward(0, th);
        if ~isfinite(yc) || abs(yc) < 1e-9, break; end
        th = th * tgt/abs(yc);
    end
    FIELDS(ff,1) = th;
    fprintf('  视场 %d：方位 %5.1f°，主光线像高标定 %+.4f mm（目标 %.4f）\n', ...
        ff, FIELDS(ff,2), traceForward(0,th), tgt);
end

%% ---- 枚举（C(13,2)=78 + 13 条含像面 = 91）----
pairs = zeros(0,2);
for aa = 1:numel(optIdx)
    for bb = aa+1:numel(optIdx)
        pairs(end+1,:) = [optIdx(aa) optIdx(bb)];
    end
end
for aa = 1:numel(optIdx)
    pairs(end+1,:) = [optIdx(aa) 15];
end
nP = size(pairs,1); nF = size(FIELDS,1);
Rc = nan(nP,nF); Rr = nan(nP,nF); Zf = nan(nP,nF); Bl = false(nP,nF); nr = zeros(nP,nF);

for qq = 1:nP
    for ff = 1:nF
        Yl = nan(PN+1,1); Ul = nan(PN+1,1);
        for pp = 0:PN
            [yy,uu,isBlk] = traceGhost(-1+2*pp/PN, FIELDS(ff,1), pairs(qq,1), pairs(qq,2));
            if ~isBlk, Yl(pp+1) = yy; Ul(pp+1) = uu; end
        end
        okf = ~isnan(Yl);
        nr(qq,ff) = sum(okf);
        if nnz(okf) < 3, Bl(qq,ff) = true; continue; end
        yv = Yl(okf); uv = Ul(okf);
        Rc(qq,ff) = mean(yv);
        Rr(qq,ff) = sqrt(mean((yv-mean(yv)).^2));
        if var(uv) > 1e-16
            C = cov(yv, uv);
            Zf(qq,ff) = -C(1,2)/var(uv);      % 最佳像面（相对像面原点的离焦）
        end
    end
end

onS = false(nP,nF);  Mg = nan(nP,nF);
for ff = 1:nF
    ph  = FIELDS(ff,2)*pi/180;
    Bd  = min(HALF_W/max(abs(cos(ph)),1e-12), HALF_H/max(abs(sin(ph)),1e-12));
    Mg(:,ff)  = Bd - Rc(:,ff);            % 正 = 中心还在传感器内，余量多少 mm
    onS(:,ff) = Mg(:,ff) >= -1e-3;
end

%% ---- 与 Zemax GUI 导出对账（轴向场）----
Zx = read_zemax_ghost(fullfile(rootDir,'zemax-ADAS','加窗口鬼影分析1-15.txt'));
mzi = nan(nP,1);
for qq = 1:nP
    r0 = find(Zx.j == pairs(qq,2) & Zx.i == pairs(qq,1), 1);
    if ~isempty(r0), mzi(qq) = r0; end
end
okm = ~isnan(mzi);
okm(okm) = Zx.rms(mzi(okm)) > 0;
qv = find(okm);
zf0 = Zf(qv,1);  zz = Zx.focus(mzi(qv));  sr = Zx.rms(mzi(qv));
good = ~isnan(zf0) & isfinite(zz);
fprintf('\n轴向对账（%d 组可比）：\n', nnz(good));
if nnz(good) > 2
    nn = find(good);
    dd = abs(zf0(nn) - zz(nn));
    near = abs(zz(nn)) < 1.0;                 % 危险带：鬼像焦点离像面 1 mm 以内
    fprintf('  鬼像焦点 vs Zemax：corr %+.4f，全 91 组中位 |Δ| %.3f mm\n', ...
        corr(zf0(nn), zz(nn)), median(dd));
    fprintf('  危险带（|Zemax 焦点距| < 1 mm，%d 组）：中位 |Δ| %.1f µm，最大 %.1f µm\n', ...
        nnz(near), 1000*median(dd(near)), 1000*max(dd(near)));
    fprintf('  光斑 RMS vs Zemax RMS：corr %+.4f，中位比值 %.2f\n', ...
        corr(Rr(qv(nn),1), sr(nn)), median(Rr(qv(nn),1)./sr(nn)));
    big = find(dd > 0.2);
    if ~isempty(big)
        fprintf('  偏差 >0.2 mm 的 %d 组（大角度/大弥散，二维子午面模型下限）：', numel(big));
        fprintf('%d-%d ', [pairs(qv(nn(big)),2), pairs(qv(nn(big)),1)]');
        fprintf('\n');
    end
end

%% ---- 表：最锐利且在传感器内的鬼影 ----
lbl = arrayfun(@(q) sprintf('%d-%d', pairs(q,2), pairs(q,1)), 1:nP, 'UniformOutput', false);
mR = Rr;  mR(~onS | nr < 6) = Inf;
[mRv, mRf] = min(mR, [], 2);
fprintf('\n%-8s %8s %10s %10s %9s %10s %8s %s\n', ...
    '面组合','最锐视场','RMS (mm)','离焦 (mm)','中心 (mm)','边界余量','光线','在屏/4');
[~, ord] = sort(mRv);
for rk = 1:12
    qq = ord(rk);
    if ~isfinite(mRv(qq)), break; end
    ff = mRf(qq);
    fprintf('%-8s %7.2f° %10.4f %10.4f %9.3f %10.3f %4d/21 %7d/4\n', lbl{qq}, ...
        FIELDS(ff,1), Rr(qq,ff), Zf(qq,ff), Rc(qq,ff), Mg(qq,ff), nr(qq,ff), sum(onS(qq,:)));
end

fprintf('\n按视场统计（%d 组 × %d 视场）：\n', nP, nF);
for ff = 1:nF
    fprintf('  %5.2f°  在传感器内 %2d   全挡 %2d   出界 %2d\n', FIELDS(ff,1), ...
        sum(onS(:,ff)), sum(Bl(:,ff)), sum(~onS(:,ff) & ~Bl(:,ff)));
end
fprintf('\n光斑中心始终在传感器内的组合：%d/%d\n', sum(all(onS,2)), nP);
fprintf('至少一个视场出界的组合：%d\n', sum(any(~onS & ~Bl, 2)));

%% ---- CSV ----
outCsv = fullfile(rootDir,'zemax-ADAS','ir_cut','data','ghost_realray_IRcut.csv');
fid = fopen(outCsv,'w','n','UTF-8');
fprintf(fid,'surface_j,surface_i,field_deg,center_mm,rms_mm,defocus_mm,margin_mm,on_sensor,blocked\n');
for qq = 1:nP
    for ff = 1:nF
        fprintf(fid,'%d,%d,%.2f,%.4f,%.4f,%.4f,%.4f,%d,%d\n', pairs(qq,2), pairs(qq,1), ...
            FIELDS(ff,1), Rc(qq,ff), Rr(qq,ff), Zf(qq,ff), Mg(qq,ff), onS(qq,ff), Bl(qq,ff));
    end
end
fclose(fid);

%% ---- 图 ----
fig = figure('Visible','off','Color','w','Position',[50 60 1820 720]);
fCol = [0 0.45 0.74; 0.85 0.33 0.10; 0.47 0.67 0.19; 0.49 0.18 0.56];
mk   = {'o','s','^','d'};
cosA = cos(FIELDS(:,2)'*pi/180);  sinA = sin(FIELDS(:,2)'*pi/180);   % 1×4

% ---- (a) 光斑中心随视场移动 ----
ax = subplot(1,2,1); hold(ax,'on');
patch(ax,[-HALF_W HALF_W HALF_W -HALF_W],[-HALF_H -HALF_H HALF_H HALF_H], ...
    [0.85 0.92 1.0],'EdgeColor',[0.2 0.4 0.7],'LineWidth',1.2,'HandleVisibility','off');
for qq = 1:nP
    plot(ax, Rc(qq,:).*cosA, Rc(qq,:).*sinA, '-', ...
        'Color',[0.82 0.84 0.86],'LineWidth',0.4,'HandleVisibility','off');
end
% 最锐利的 6 组单独描出并标注
[~, o5] = sort(mRv);
top6 = o5(1:min(6, nnz(isfinite(mRv))));
for rk = 1:numel(top6)
    qq = top6(rk);
    plot(ax, Rc(qq,:).*cosA, Rc(qq,:).*sinA, '-', 'Color',[0.78 0.20 0.18], ...
        'LineWidth', 1.5, 'HandleVisibility','off');
    xl = Rc(qq,3)*cosA(3); yl = Rc(qq,3)*sinA(3);
    if ~isnan(xl)
        text(ax, xl+0.10, yl-0.42+0.28*rk, lbl{qq}, 'FontSize', 8.5, ...
            'Color',[0.78 0.20 0.18]);
    end
end
h = gobjects(1,nF);
for ff = 1:nF
    xf = Rc(:,ff).*cos(FIELDS(ff,2)*pi/180);
    yf = Rc(:,ff).*sin(FIELDS(ff,2)*pi/180);
    okp = ~isnan(xf) & ~isnan(yf);
    h(ff) = scatter(ax, xf(okp), yf(okp), 26, fCol(ff,:), mk{ff}, 'filled', ...
        'MarkerFaceAlpha',0.75);
end
xlim(ax,[-8.2 6.2]); ylim(ax,[-3.6 3.6]); axis(ax,'equal');
grid(ax,'on'); box(ax,'off');
xlabel(ax,'x (mm)'); ylabel(ax,'y (mm)');
legend(ax, h, {'0°（中心）','8.66°（竖半幅）','15.06°（横半幅）','17.22°（对角）'}, ...
    'Location','southwest','FontSize',9);
title(ax, sprintf('(a) %d 组鬼影光斑中心随视场移动（蓝框 = 8.08×4.58 mm 传感器）', nP), ...
    'FontSize', 10.5);

% ---- (b) 锐度随视场的变化（右侧越靠下越危险）----
ax2 = subplot(1,2,2); hold(ax2,'on');
nB = 8;
[~, o8] = sort(mRv);
top8 = o8(1:min(nB, nnz(isfinite(mRv))));
cB = lines(numel(top8));
ye = nan(numel(top8),1);
for rk = 1:numel(top8)
    qq = top8(rk);
    yv = 1000*Rr(qq,:);
    yv(Bl(qq,:) | nr(qq,:) < 3) = NaN;         % 全挡的视场不画
    semilogy(ax2, FIELDS(:,1)', yv, '-o', 'Color', cB(rk,:), ...
        'MarkerFaceColor', cB(rk,:), 'MarkerSize', 5, 'LineWidth', 1.4);
    c = find(isfinite(yv), 1, 'last');
    if ~isempty(c), ye(rk) = yv(c); end
end
% 末值相近的标签按 1.22 倍阶梯上推，避免叠字
[~, so] = sort(ye);
for ii = 2:numel(so)
    if ye(so(ii)) < ye(so(ii-1))*1.22, ye(so(ii)) = ye(so(ii-1))*1.22; end
end
for rk = 1:numel(top8)
    if isnan(ye(rk)), continue; end
    text(ax2, FIELDS(end,1)+0.45, ye(rk), lbl{top8(rk)}, 'FontSize', 8.5, ...
        'Color', cB(rk,:), 'VerticalAlignment','middle');
end
set(ax2,'YScale','log');
xlim(ax2, [-0.6, FIELDS(end,1)+2.2]);
grid(ax2,'on'); box(ax2,'off');
xlabel(ax2, '视场角 (°，沿各自方位)');
ylabel(ax2, '鬼影 RMS 光斑半径 (µm，log)');
title(ax2, '(b) 最锐 8 组的锐度随视场变化：曲线越往下越危险', 'FontSize', 10.5);

sgtitle('鬼影随视场行为　15mm F/1.4 + IR-CUT/CG 板　|　二维子午面实光线追迹，91 组 × 4 视场', ...
    'FontSize', 12);
set(findall(fig,'-property','FontName'),'FontName','Microsoft YaHei');
set(findall(fig,'-property','FontSize'),'FontSize',9);
outPng = fullfile(rootDir,'zemax-ADAS','ir_cut','figs','ghost_realray_fields_IRcut.png');
exportgraphics(fig, outPng, 'Resolution', 300); close(fig);
fprintf('\nCSV: %s\n图: %s\n', outCsv, outPng);

% ================= 嵌套函数 =================
    function [sag,dzd] = sagf(k,y)
        r = abs(y); sag = 0; dzd = 0;
        if r == 0, return; end
        disc = 1-(1+kk(k))*c(k)^2*r^2;
        if disc <= 0, sag = NaN; dzd = NaN; return; end
        sq = sqrt(disc);
        sag = c(k)*r^2/(1+sq) + A4(k)*r^4 + A6(k)*r^6;
        dzd = c(k)*r/sq + 4*A4(k)*r^3 + 6*A6(k)*r^5;
    end

    function [y2,z2,dy2,dz2,ok] = hit(k,y0,z0,dy,dz)
        y2 = NaN; z2 = NaN; dy2 = dy; dz2 = dz; ok = false;
        if abs(dz) < 1e-12, return; end
        if abs(Z(k)-z0) < 1e-12 && c(k) == 0          % 零间隙面（S14 与像面重合）
            y2 = y0; z2 = z0; ok = abs(y0) <= SD(k) + 1e-6; return;
        end
        g = @(s)(z0+s*dz) - (Z(k)+sagf(k, y0+s*dy));
        s0 = (Z(k)-z0)/dz;
        span = 1.6*abs(s0) + 1.0;
        cand = linspace(-0.02*abs(s0), span, 60);
        gv = arrayfun(g, cand);
        s = NaN;
        for t = 1:numel(cand)-1
            if isfinite(gv(t)) && isfinite(gv(t+1)) && gv(t)*gv(t+1) <= 0
                s = fzero(g, [cand(t) cand(t+1)]); break;
            end
        end
        if ~isfinite(s), return; end
        y2 = y0+s*dy; z2 = z0+s*dz;
        if abs(y2) > SD(k) + 1e-6, return; end   % 边缘光线正好踩在口径上，留数值余量
        ok = true;
    end

    function [dy2,dz2] = rfr(n1,n2,dy,dz,k,y)
        [~,dzd] = sagf(k,y);
        if ~isfinite(dzd), dy2 = NaN; dz2 = NaN; return; end
        Ny = -sign(y)*dzd; Nz = 1;
        Nn = hypot(Ny,Nz); Ny = Ny/Nn; Nz = Nz/Nn;
        if dy*Ny+dz*Nz > 0, Ny = -Ny; Nz = -Nz; end
        cosI = -(dy*Ny+dz*Nz);
        mu = n1/n2; sin2T = mu^2*(1-cosI^2);
        if sin2T > 1, dy2 = NaN; dz2 = NaN; return; end
        cosT = sqrt(1-sin2T);
        dy2 = mu*dy + (mu*cosI-cosT)*Ny;
        dz2 = mu*dz + (mu*cosI-cosT)*Nz;
        nn = hypot(dy2,dz2); dy2 = dy2/nn; dz2 = dz2/nn;
    end

    function [dy2,dz2] = rfl(dy,dz,k,y)
        [~,dzd] = sagf(k,y);
        Ny = -sign(y)*dzd; Nz = 1; Nn = hypot(Ny,Nz); Ny = Ny/Nn; Nz = Nz/Nn;
        dd = dy*Ny+dz*Nz; dy2 = dy-2*dd*Ny; dz2 = dz-2*dd*Nz;
    end

    function y1 = startHeight(p,th)
        target = p*Rstop; tanT = tan(th*pi/180);
        h = @(y) stopPlaneHeight(y,tanT) - target;
        ysx = linspace(-11,11,45); hsx = arrayfun(h, ysx);
        y1 = NaN;
        for t = 1:numel(ysx)-1
            if isfinite(hsx(t)) && isfinite(hsx(t+1)) && hsx(t)*hsx(t+1) <= 0
                y1 = fzero(h,[ysx(t) ysx(t+1)]); return;
            end
        end
    end

    function yh = stopPlaneHeight(y1,tanT)
        dz = 1/sqrt(1+tanT^2); dy = tanT*dz;
        y = y1-5*tanT; z = Z(1)-5; yh = NaN;
        for k = 1:4
            [y,z,dy,dz,ok] = hit(k,y,z,dy,dz); if ~ok, return; end
            n1 = 1; if k > 1, n1 = nA(k-1); end
            [dy,dz] = rfr(n1, nA(k), dy, dz, k, y); if ~isfinite(dy), return; end
        end
        yh = y + (Z(5)-z)*dy/dz;
    end

    function [yimg,slope] = traceForward(p,th)
        y1 = startHeight(p,th); tanT = tan(th*pi/180);
        dz = 1/sqrt(1+tanT^2); dy = tanT*dz;
        y = y1-5*tanT; z = Z(1)-5;
        for k = 1:NOPT
            [y,z,dy,dz,ok] = hit(k,y,z,dy,dz);
            if ~ok, yimg = NaN; slope = NaN; return; end
            n1 = 1; if k > 1, n1 = nA(k-1); end
            [dy,dz] = rfr(n1, nA(k), dy, dz, k, y);
            if ~isfinite(dy), yimg = NaN; slope = NaN; return; end
        end
        yimg = y + (Z(NS)-z)*dy/dz; slope = dy/dz;
    end

    function [yimg,slope,blocked] = traceGhost(p,thdeg,i,j)
        % j = 第一次反射面（靠后），i = 第二次反射面（靠前）
        yimg = NaN; slope = NaN; blocked = true;
        y1 = startHeight(p,thdeg); if ~isfinite(y1), return; end
        tanT = tan(thdeg*pi/180);
        dz = 1/sqrt(1+tanT^2); dy = tanT*dz;
        y = y1-5*tanT; z = Z(1)-5;
        for k = 1:j-1
            [y,z,dy,dz,ok] = hit(k,y,z,dy,dz); if ~ok, return; end
            n1 = 1; if k > 1, n1 = nA(k-1); end
            [dy,dz] = rfr(n1, nA(k), dy, dz, k, y); if ~isfinite(dy), return; end
        end
        [y,z,dy,dz,ok] = hit(j,y,z,dy,dz); if ~ok, return; end
        [dy,dz] = rfl(dy,dz,j,y);
        for k = j-1:-1:i+1
            [y,z,dy,dz,ok] = hit(k,y,z,dy,dz); if ~ok, return; end
            [dy,dz] = rfr(nA(k), nA(k-1), dy, dz, k, y); if ~isfinite(dy), return; end
        end
        [y,z,dy,dz,ok] = hit(i,y,z,dy,dz); if ~ok, return; end
        [dy,dz] = rfl(dy,dz,i,y);
        for k = i+1:NOPT
            [y,z,dy,dz,ok] = hit(k,y,z,dy,dz); if ~ok, return; end
            [dy,dz] = rfr(nA(k-1), nA(k), dy, dz, k, y); if ~isfinite(dy), return; end
        end
        yimg = y + (Z(NS)-z)*dy/dz; slope = dy/dz; blocked = false;
    end
end

%% ================= 文件级函数 =================
function Z = read_zemax_ghost(fn)
    fid = fopen(fn,'rb');
    b = fread(fid, inf, 'uint8=>uint8'); fclose(fid);
    if numel(b) > 2 && b(1) == 255 && b(2) == 254, b = b(3:end); end
    u = uint16(b(1:2:end)) + 256*uint16(b(2:2:end));
    L = strtrim(splitlines(string(char(u(:)'))));
    % 必须逐块解析：追迹失败的行没有「到鬼像焦点」行，顺序追加会让后面全体错位
    Z.j = []; Z.i = []; Z.edge = []; Z.rms = []; Z.focus = [];
    cur = []; row = []; foc = NaN;
    for k = 1:numel(L)
        s = L(k);
        tk = regexp(s, '鬼像反射(\d+)然后(\d+)', 'tokens', 'once');
        if ~isempty(tk)
            [Z, cur, row, foc] = flush_block(Z, cur, row, foc);
            cur = [str2double(tk{2}), str2double(tk{1})];   % [i j] = [第二, 第一]
            continue;
        end
        if isempty(cur), continue; end
        f = regexp(s, '\S+', 'match');
        if numel(f) >= 4 && strcmp(f{1},'15')
            num = str2double(f(2:4));
            if all(~isnan(num)), row = num(:)'; end
            continue;
        end
        v = regexp(s, '^到鬼像焦点的距离\s*:\s*(-?[\d.E+-]+)', 'tokens', 'once');
        if ~isempty(v), foc = str2double(v{1}); end
    end
    [Z, ~, ~, ~] = flush_block(Z, cur, row, foc);
end

function [Z, cur, row, foc] = flush_block(Z, cur, row, foc)
    if ~isempty(cur) && ~isempty(row)
        Z.j(end+1,1)     = cur(2);
        Z.i(end+1,1)     = cur(1);
        Z.edge(end+1,1)  = row(1);
        Z.rms(end+1,1)   = row(3);
        Z.focus(end+1,1) = foc;      % 没有这一行就是 NaN，不往后挤
    end
    cur = []; row = []; foc = NaN;
end
