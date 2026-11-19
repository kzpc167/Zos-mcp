function ghost_realray_20261119()
%% 鬼影实光线模型 —— 二维子午面 + conic/非球面 + 矢量 Snell
% 1) 把边缘高度/RMS 从近轴升级为实光线；2) 回答离轴视场鬼影是否扫进传感器
% 旋转对称 ⇒ 任一方位场点等价于"坐标轴转到该方向的子午面"，二维追迹精确
clc; close all;
rootDir = 'D:\Zemax-mcp';
outCsv = fullfile(rootDir,'matlab','data','ghost_realray.csv');
outPng = fullfile(rootDir,'zemax-ADAS','layouts','ghost_realray_fields.png');

R  = [ 30.292444786227495; 15.440361836161781; 19.594321598855050; -28.689051655560153; ...
       Inf; 10.656502330960160; -37.872933789988410; 5.594418893802987; ...
       14.149580890275338; -13.331179488826633; -6.521622827840516; -56.541840514082146; Inf];
kk = [-1;0;0;0;0;0;0;0;0;0;-1;0;0];
A4 = [-6e-05;0;0;0;0;0;0;0;0;0; 6.90555553198994e-04;0;0];
A6 = [-1.7562105437933684e-07;0;0;0;0;0;0;0;0;0; 4.271605316481686e-06;0;0];
T  = [ 3.5013748687257498; 4.009718879528294; 4.691545319874674; 0.48843594697988135; ...
       0.4620509464435005; 3.8334903419576944; 2.5385774758098383; 3.320384692962178; ...
       4.21145629161534; 1.232440025221863; 1.3097885426424138; 0.900736492595912; 0];
nA = [1.58144;1;1.77288;1;1;1.77400;1.80518;1;1.77288;1;1.48749;1;1];
SD = [8;8;7;7;5.206100602387041;5.5;5;3.8;5.5;5.5;5;5;4.6562946122908855];
c  = zeros(13,1); mskR = isfinite(R); c(mskR)=1./R(mskR);
Z  = cumsum([0;T(1:12)]);  Rstop = SD(5);
HALF_W = 4.04; HALF_H = 2.29;
FIELDS = [0 90; 8.75 90; 15 90; 17.43 29.96];
optIdx = [1 2 3 4 6 7 8 9 10 11 12];
PN = 20;

% ---- 自检：正常系统边缘光线 ----
[yN,uN] = traceForward(1,0);
uAng = atan(uN);
fprintf('自检：正常系统边缘光线 像高 %.4f mm，像方角 %.2f°（F/%.2f）\n', ...
    yN, abs(uAng)*180/pi, 1/(2*abs(tan(uAng))));

% ---- 枚举组合 ----
pairs = zeros(0,2);
for aa=1:numel(optIdx), for bb=aa+1:numel(optIdx), pairs(end+1,:)=[optIdx(aa) optIdx(bb)]; end, end
for aa=1:numel(optIdx), pairs(end+1,:)=[optIdx(aa) 13]; end
nP = size(pairs,1); nF = 4;
Rc = nan(nP,nF); Rr = nan(nP,nF); Zf = nan(nP,nF); Bl = false(nP,nF); nr = zeros(nP,nF);
for qq = 1:nP
    for ff = 1:nF
        Yl = nan(PN+1,1); Ul = nan(PN+1,1);
        for pp = 0:PN
            [yy,uu,isBlk] = traceGhost(-1+2*pp/PN, FIELDS(ff,1), pairs(qq,1), pairs(qq,2));
            if ~isBlk, Yl(pp+1)=yy; Ul(pp+1)=uu; end
        end
        okf = ~isnan(Yl);
        nr(qq,ff) = sum(okf);
        if ~any(okf), Bl(qq,ff)=true; continue; end
        yv = Yl(okf); Rc(qq,ff)=mean(yv);
        Rr(qq,ff)=sqrt(mean((yv-mean(yv)).^2));
        idx = find(okf,1,'last');
        if abs(Ul(idx))>1e-9, Zf(qq,ff) = -Yl(idx)/Ul(idx); end
    end
end
onS = false(nP,nF);
for ff=1:nF
    ph = FIELDS(ff,2)*pi/180;
    onS(:,ff) = abs(Rc(:,ff)*cos(ph))<=HALF_W & abs(Rc(:,ff)*sin(ph))<=HALF_H;
end

% ---- 与 Zemax 对账 ----
Zt = readtable(fullfile(rootDir,'matlab','data','ghost_zemax_20261119.csv'));
mz = nan(nP,1);
for qq=1:nP
    r0 = find(Zt.j_surface==pairs(qq,2) & Zt.i_surface==pairs(qq,1),1);
    if ~isempty(r0), mz(qq)=r0; end
end
has = ~isnan(mz);
okm = false(nP,1); okm(has) = Zt.rms_mm(mz(has))>0;
qv = find(okm); az = Zt(mz(okm),:);
fprintf('\n轴向对账（%d 组）：\n', sum(okm));
d0 = Zf(qv,1) - az.d_focus_mm;
dB = Zf(qv,1) - 0.900736 - az.d_focus_mm;
fprintf('  焦点原点检验：以像面为原点 中位偏差 %+8.3f mm；再减 BFL 后 %+8.3f mm\n', ...
    median(d0,'omitnan'), median(dB,'omitnan'));
C3 = corrcoef(Zf(qv,1), az.d_focus_mm);
fprintf('  鬼像焦点 vs Zemax：corr %+.4f  最大偏差 %.4f mm\n', C3(1,2), max(abs(d0)));
C2 = corrcoef(Rr(qv,1), az.rms_mm);
fprintf('  RMS 半径 vs Zemax RMS：corr %+.4f  中位比值 %.3f\n', C2(1,2), median(Rr(qv,1)./az.rms_mm));
edgeOur = Rr(qv,1);
C1 = corrcoef(edgeOur, abs(az.edge_mm));
fprintf('  光斑外缘 vs |Zemax 边缘高度|：corr %+.4f  中位比值 %.3f\n', ...
    C1(1,2), median(edgeOur./abs(az.edge_mm)));
[~,wo] = sort(abs(d0),'descend');
fprintf('  焦点偏差最大的 5 组：\n');
for q = 1:5
    kk = qv(wo(q));
    fprintf('    %2d-%-2d  实光线 %9.3f   Zemax %9.3f   差 %+7.3f\n', ...
        pairs(kk,2), pairs(kk,1), Zf(kk,1), az.d_focus_mm(wo(q)), d0(wo(q)));
end

% ---- 表：最锐利且在传感器内的鬼影 ----
lbl = arrayfun(@(qq) sprintf('%d-%d',pairs(qq,2),pairs(qq,1)),1:nP,'UniformOutput',false);
mR = Rr; mR(~onS | nr < 6) = Inf; [mRv, mRf] = min(mR,[],2);
fprintf('\n%-8s %8s %10s %10s %9s %6s %s\n','面组合','最锐视场','RMS (mm)','焦点 (mm)','中心 (mm)','光线','落进传感器');
[~,ord] = sort(mRv);
for rr=1:12
    qq=ord(rr);
    if ~isfinite(mRv(qq)), break; end
    ff = mRf(qq);
    fprintf('%-8s %8.2f° %10.3f %10.3f %9.3f %4d/21  %d/4\n',lbl{qq},FIELDS(ff,1), ...
        Rr(qq,ff),Zf(qq,ff),Rc(qq,ff),nr(qq,ff),sum(onS(qq,:)));
end

fprintf('\n按视场统计（%d 组 × %d 视场）：\n', nP, nF);
for ff=1:nF
    fprintf('  %5.2f°  在传感器内 %2d  全挡 %2d  出界 %2d\n', FIELDS(ff,1), ...
        sum(onS(:,ff)), sum(Bl(:,ff)), sum(~onS(:,ff) & ~Bl(:,ff)));
end
q15 = find(~onS(:,3) & ~Bl(:,3));
fprintf('  15° 出界的 %d 组：', numel(q15));
fprintf('%s ', lbl{q15}); fprintf('\n');
fprintf('\n光斑中心始终在传感器内的组合：%d/%d；存在被全挡视场的组合：%d\n', ...
    sum(all(onS,2)), nP, sum(any(Bl,2)));

fid=fopen(outCsv,'w','n','UTF-8');
fprintf(fid,'surface_j,surface_i,field_deg,center_mm,rms_mm,focus_mm,on_sensor,blocked\n');
for qq=1:nP
    for ff=1:nF
        fprintf(fid,'%d,%d,%.2f,%.4f,%.4f,%.4f,%d,%d\n',pairs(qq,2),pairs(qq,1), ...
            FIELDS(ff,1),Rc(qq,ff),Rr(qq,ff),Zf(qq,ff),onS(qq,ff),Bl(qq,ff));
    end
end
fclose(fid);

fig=figure('Visible','off','Color','w','Position',[60 60 1120 720]); ax=axes(fig); hold(ax,'on');
patch(ax,[-HALF_W HALF_W HALF_W -HALF_W],[-HALF_H -HALF_H HALF_H HALF_H], ...
    [0.85 0.92 1.0],'EdgeColor',[0.2 0.4 0.7],'LineWidth',1.2,'HandleVisibility','off');
fCol = [0 0.45 0.74; 0.85 0.33 0.10; 0.47 0.67 0.19; 0.49 0.18 0.56];
mk = {'o','s','^','d'};
for qq=1:nP
    xs = Rc(qq,:).*cos(FIELDS(:,2)'*pi/180);
    yv = Rc(qq,:).*sin(FIELDS(:,2)'*pi/180);
    plot(ax,xs,yv,'-','Color',[0.76 0.78 0.80],'LineWidth',0.5,'HandleVisibility','off');
end
h = gobjects(1,nF);
for ff=1:nF
    xf = Rc(:,ff).*cos(FIELDS(ff,2)*pi/180);
    yf = Rc(:,ff).*sin(FIELDS(ff,2)*pi/180);
    okp = ~isnan(xf) & ~isnan(yf);
    h(ff) = scatter(ax,xf(okp),yf(okp),30,fCol(ff,:),mk{ff},'filled','MarkerEdgeColor','none');
end
xlim(ax,[-6 6]); ylim(ax,[-5 5.5]); axis(ax,'equal'); grid(ax,'on'); box(ax,'off');
xlabel(ax,'x (mm)'); ylabel(ax,'y (mm)');
legend(ax,h,{'0°','8.75°','15°','17.43°（对角）'},'Location','southwest','FontSize',9);
title(ax,'66 组鬼影光斑中心随视场移动（蓝框 = 8.08×4.58 mm 传感器）','FontSize',11);
set(findall(fig,'-property','FontName'),'FontName','Microsoft YaHei');
set(findall(fig,'-property','FontSize'),'FontSize',9);
exportgraphics(fig,outPng,'Resolution',300); close(fig);
fprintf('\nCSV: %s\n图: %s\n',outCsv,outPng);

% ================= 嵌套函数 =================
    function [sag,dzd] = sagf(k,y)
        r=abs(y); sag=0; dzd=0;
        if r==0, return; end
        disc = 1-(1+kk(k))*c(k)^2*r^2;
        if disc<=0, sag=NaN; dzd=NaN; return; end
        sq=sqrt(disc);
        sag = c(k)*r^2/(1+sq)+A4(k)*r^4+A6(k)*r^6;
        dzd = c(k)*r/sq+4*A4(k)*r^3+6*A6(k)*r^5;
    end

    function [y2,z2,dy2,dz2,ok] = hit(k, y0,z0,dy,dz)
        y2=NaN; z2=NaN; dy2=dy; dz2=dz; ok=false;
        if abs(dz)<1e-12, return; end
        g=@(s)(z0+s*dz)-(Z(k)+sagf(k,y0+s*dy));
        s0=(Z(k)-z0)/dz;
        span = 1.6*abs(s0) + 1.0;
        cand = linspace(-0.02*abs(s0), span, 60);
        gv = arrayfun(g, cand);
        s = NaN;
        for t = 1:numel(cand)-1
            if isfinite(gv(t)) && isfinite(gv(t+1)) && gv(t)*gv(t+1) <= 0
                s = fzero(g,[cand(t) cand(t+1)]); break;
            end
        end
        if ~isfinite(s), return; end
        y2=y0+s*dy; z2=z0+s*dz;
        if abs(y2)>SD(k), return; end
        ok=true;
    end

    function [dy2,dz2] = rfr(n1,n2,dy,dz,k,y)
        [~,dzd]=sagf(k,y);
        if ~isfinite(dzd), dy2=NaN; dz2=NaN; return; end
        Ny=-sign(y)*dzd; Nz=1;
        Nn=hypot(Ny,Nz); Ny=Ny/Nn; Nz=Nz/Nn;
        if dy*Ny+dz*Nz>0, Ny=-Ny; Nz=-Nz; end
        cosI=-(dy*Ny+dz*Nz);
        mu=n1/n2; sin2T=mu^2*(1-cosI^2);
        if sin2T>1, dy2=NaN; dz2=NaN; return; end
        cosT=sqrt(1-sin2T);
        dy2=mu*dy+(mu*cosI-cosT)*Ny;
        dz2=mu*dz+(mu*cosI-cosT)*Nz;
        nn=hypot(dy2,dz2); dy2=dy2/nn; dz2=dz2/nn;
    end

    function [dy2,dz2] = rfl(dy,dz,k,y)
        [~,dzd]=sagf(k,y);
        Ny=-sign(y)*dzd; Nz=1; Nn=hypot(Ny,Nz); Ny=Ny/Nn; Nz=Nz/Nn;
        dd=dy*Ny+dz*Nz; dy2=dy-2*dd*Ny; dz2=dz-2*dd*Nz;
    end

    function y1 = startHeight(p,th)
        target = p*Rstop; tanT=tan(th*pi/180);
        h=@(y) stopPlaneHeight(y,tanT)-target;
        ysx = linspace(-11,11,45); hsx = arrayfun(h, ysx);
        y1 = NaN;
        for t = 1:numel(ysx)-1
            if isfinite(hsx(t)) && isfinite(hsx(t+1)) && hsx(t)*hsx(t+1) <= 0
                y1 = fzero(h,[ysx(t) ysx(t+1)]); return;
            end
        end
    end

    function yh = stopPlaneHeight(y1,tanT)
        dz=1/sqrt(1+tanT^2); dy=tanT*dz;
        y=y1-5*tanT; z=Z(1)-5; yh=NaN;
        for k=1:4
            [y,z,dy,dz,ok]=hit(k,y,z,dy,dz); if ~ok, return; end
            n1=1; if k>1, n1=nA(k-1); end
            [dy,dz]=rfr(n1,nA(k),dy,dz,k,y); if ~isfinite(dy), return; end
        end
        yh = y + (Z(5)-z)*dy/dz;
    end

    function [yimg,slope] = traceForward(p,th)
        y1=startHeight(p,th); tanT=tan(th*pi/180);
        dz=1/sqrt(1+tanT^2); dy=tanT*dz;
        y=y1-5*tanT; z=Z(1)-5;
        for k=1:12
            [y,z,dy,dz,ok]=hit(k,y,z,dy,dz);
            if ~ok, yimg=NaN; slope=NaN; return; end
            n1=1; if k>1, n1=nA(k-1); end
            [dy,dz]=rfr(n1,nA(k),dy,dz,k,y);
            if ~isfinite(dy), yimg=NaN; slope=NaN; return; end
        end
        yimg=y+(Z(13)-z)*dy/dz; slope=dy/dz;
    end

    function [yimg,slope,blocked] = traceGhost(p,thdeg,i,j)
        yimg=NaN; slope=NaN; blocked=true;
        y1=startHeight(p,thdeg); if ~isfinite(y1), return; end
        tanT=tan(thdeg*pi/180);
        dz=1/sqrt(1+tanT^2); dy=tanT*dz;
        y=y1-5*tanT; z=Z(1)-5;
        for k=1:j-1
            [y,z,dy,dz,ok]=hit(k,y,z,dy,dz); if ~ok, return; end
            n1=1; if k>1, n1=nA(k-1); end
            [dy,dz]=rfr(n1,nA(k),dy,dz,k,y); if ~isfinite(dy), return; end
        end
        [y,z,dy,dz,ok]=hit(j,y,z,dy,dz); if ~ok, return; end
        [dy,dz]=rfl(dy,dz,j,y);
        for k=j-1:-1:i+1
            [y,z,dy,dz,ok]=hit(k,y,z,dy,dz); if ~ok, return; end
            [dy,dz]=rfr(nA(k),nA(k-1),dy,dz,k,y); if ~isfinite(dy), return; end
        end
        [y,z,dy,dz,ok]=hit(i,y,z,dy,dz); if ~ok, return; end
        [dy,dz]=rfl(dy,dz,i,y);
        for k=i+1:12
            [y,z,dy,dz,ok]=hit(k,y,z,dy,dz); if ~ok, return; end
            [dy,dz]=rfr(nA(k-1),nA(k),dy,dz,k,y); if ~isfinite(dy), return; end
        end
        yimg=y+(Z(13)-z)*dy/dz; slope=dy/dz; blocked=false;
    end
end
