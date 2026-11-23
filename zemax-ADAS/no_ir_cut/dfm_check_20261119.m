%% DFM 几何核算（15 mm F/1.4 六片定心版）
% 边厚 / 中心边厚比 / 径厚比 / 弯曲因子 B / 定心系数 Z / 球心距 / 半球 / 非球面斜率
% 口径一律用 LDE 半口径的 2 倍（机械口径 D）
clear; clc;

R  = [30.292444786227495; 15.440361836161781; 19.594321598855050; -28.689051655560153; ...
      Inf; 10.656502330960160; -37.872933789988410; 5.594418893802987; ...
      14.149580890275338; -13.331179488826633; -6.521622827840516; -56.541840514082146];
T  = [3.5013748687257498; 4.009718879528294; 4.691545319874674; 0.48843594697988135; ...
      0.4620509464435005; 3.8334903419576944; 2.5385774758098383; 3.320384692962178; ...
      4.21145629161534; 1.232440025221863; 1.3097885426424138; 0.900736492595912];
SD = [8; 8; 7; 7; 5.206100602387041; 5.5; 5; 3.8; 5.5; 5.5; 5; 5];
kk = zeros(12,1); kk([1 11]) = -1;
A4 = zeros(12,1); A6 = zeros(12,1);
A4(1)  = -6e-05;               A6(1)  = -1.7562105437933684e-07;
A4(11) =  6.90555553198994e-04; A6(11) =  4.271605316481686e-06;
c = zeros(12,1); f = isfinite(R); c(f) = 1./R(f);

pieces = [1 2; 3 4; 6 7; 7 8; 9 10; 11 12];
names  = {'L1','L2','L3','L4','L5','L6'};
mats   = {'H-QF50A','D-LAF50-25','D-LAF50','H-ZF7LA','D-LAF50-25','H-QK3L'};

fprintf('%-4s %-11s %7s %7s %7s %7s %6s %6s %7s %6s %9s\n', ...
    '件','材料','CT','sag前','sag后','ET','SD/CT','D/CT','B','Z','|R1-R2|');
for i = 1:6
    s1 = pieces(i,1); s2 = pieces(i,2);
    CT = T(s1);
    g1 = local_sag(s1, SD(s1), c, kk, A4, A6);
    g2 = local_sag(s2, SD(s2), c, kk, A4, A6);
    ET = CT + g2 - g1;
    D1 = 2*SD(s1); D2 = 2*SD(s2);
    B  = (R(s2)+R(s1))/(R(s2)-R(s1));
    if sign(R(s1)) == sign(R(s2))            % 弯月：曲率相减
        Z = abs(D1/abs(R(s1)) - D2/abs(R(s2)))/4;
    else                                     % 双凸/双凹：曲率相加
        Z = (D1/abs(R(s1)) + D2/abs(R(s2)))/4;
    end
    fprintf('%-4s %-11s %7.3f %7.3f %7.3f %7.3f %6.2f %6.2f %7.2f %6.3f %9.2f\n', ...
        names{i}, mats{i}, CT, g1, g2, ET, SD(s1)/CT, D1/CT, B, Z, abs(R(s1)-R(s2)));
end

fprintf('\n半球判据（R / (0.7·D) < 1 即关注）：\n');
for s = 1:12
    if ~isfinite(R(s)), continue; end
    q = abs(R(s))/(0.7*2*SD(s));
    tag = ''; if q < 1, tag = '  <-- 关注'; end
    fprintf('  S%-2d R=%9.3f  D=%5.1f  R/(0.7D)=%.3f%s\n', s, R(s), 2*SD(s), q, tag);
end

fprintf('\n非球面斜率（矢高导数，按通光半口径扫描）：\n');
for s = [1 11]
    rr = linspace(0, SD(s), 4001);
    dd = local_dzdr(s, rr, c, kk, A4, A6);
    [mx, ix] = max(abs(dd));
    ang = atan(mx)*180/pi;
    sg  = sign(dd(abs(dd) > 1e-6));
    nch = sum(diff(sg) ~= 0);
    fprintf('  S%-2d 最大斜率 %.2f°（r=%.2f mm），边缘 %.2f°，斜率反号 %d 次\n', ...
        s, ang, rr(ix), atan(abs(local_dzdr(s, SD(s), c, kk, A4, A6)))*180/pi, nch);
end

fprintf('\n中心空气间隔：\n');
lbl = {'S2-S3','S4-STOP','STOP-S6','S8-S9','S10-S11','S12-像面'};
idx = [2 4 5 8 10 12];
for i = 1:6
    tag = ''; if idx(i) <= 8 && T(idx(i)) < 0.5, tag = '  <-- 关注(<0.5)'; end
    fprintf('  %-9s %.4f mm%s\n', lbl{i}, T(idx(i)), tag);
end

function g = local_sag(k, r, c, kk, A4, A6)
    disc = 1-(1+kk(k))*c(k)^2*r^2;
    if disc <= 0, g = NaN; return; end
    g = c(k)*r^2/(1+sqrt(disc)) + A4(k)*r^4 + A6(k)*r^6;
end

function d = local_dzdr(k, r, c, kk, A4, A6)
    disc = 1-(1+kk(k))*c(k)^2*r.^2;
    d = c(k)*r./sqrt(disc) + 4*A4(k)*r.^3 + 6*A6(k)*r.^5;
end
