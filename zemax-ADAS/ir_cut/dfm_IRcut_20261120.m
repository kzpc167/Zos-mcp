function dfm_IRcut_20261120()
%% DFM 逐片校核（spherical-lens-dfm-review §2/§3/§6）
% 输入：本版 LDE（半口径为机械口径，见报告 §3.6 注）
% 输出：控制台表 + zemax-ADAS/ir_cut/data/dfm_IRcut.csv
% 口径：Z 用本项目约定 Z = ¼|D1/R1 − D2/R2|（Karow 口径 = 4Z）
clc; close all;
rootDir = fileparts(fileparts(mfilename('fullpath')));

%% ---------------- 元件表（逐片，胶合组拆成两片）----------------
% 胶合组只在「胶合工艺」那几项上按组算（见文末），几何与定心一律逐片。
% name  s1 s2   R1        R2        CT      SD1  SD2   glass          k      A4          A6
E = {
 'L1'    1  2   34.7804   17.4357   3.3078  8.00 8.00  'H-QF50A'       -1  -6.500e-05   -1.854e-07
 'L2'    3  4   20.5303  -28.5956   4.0797  7.00 7.00  'D-LAF50-25'    0   0           0
 'L3'    6  7   10.3528  -38.1772   4.0737  5.50 5.00  'D-LAF50'       0   0           0
 'L4'    7  8  -38.1772    5.6242   2.0390  5.00 3.80  'H-ZF7LA'       0   0           0
 'L6'    9 10   14.0340  -12.0524   4.2887  5.50 5.50  'D-LAF50-25'    0   0           0
 'L7'   11 12   -6.4076   Inf       1.3510  5.00 5.00  'H-QK3L'       -1   6.299414e-04  2.372824e-07
 '窗口' 13 14   Inf       Inf       0.4000  4.681 4.650 'H-K9L'         0   0           0
};
nE = size(E,1);

sag = @(R,k,A4,A6,h) s_sag(R,k,A4,A6,h);

printf_header();
rows = zeros(0,10);
for q = 1:nE
    nm = E{q,1};  s1 = E{q,2};  s2 = E{q,3};
    R1 = E{q,4};  R2 = E{q,5};  CT = E{q,6};
    SD1 = E{q,7}; SD2 = E{q,8}; gl = E{q,9};
    kk = E{q,10}; A4 = E{q,11}; A6 = E{q,12};
    h  = max(SD1,SD2);  D1 = 2*SD1;  D2 = 2*SD2;  Dmax = 2*max(SD1,SD2);
    % ET 按最大机械口径算（与 check_manufacturability 口径一致）；s2 在本设计里全是球面
    z1 = sag(R1,kk,A4,A6,h);  z2 = sag(R2,0,0,0,h);
    ET = CT + z2 - z1;
    ratio = CT/ET;
    DCT   = Dmax/CT;

    if isinf(R1) && isinf(R2)
        Z = NaN;  dr = NaN;
    else
        t1 = 0; if isfinite(R1), t1 = D1/R1; end
        t2 = 0; if isfinite(R2), t2 = D2/R2; end
        Z = 0.25*abs(t1 - t2);
        if isfinite(R1) && isfinite(R2)
            dr = abs(R1 - R2 - CT);                      % 两球心距
        else
            dr = NaN;
        end
    end

    % 半球判据按「该面自己的口径」算，不用元件最大口径
    hemis = false;
    if isfinite(R1) && abs(R1) <= 0.7*D1, hemis = true; end
    if isfinite(R2) && abs(R2) <= 0.7*D2, hemis = true; end
    rmin  = min(abs([R1 R2]));
    hmg   = Inf;                                   % 半球余量 = min(|R| − 0.7·D)
    if isfinite(R1), hmg = min(hmg, abs(R1) - 0.7*D1); end
    if isfinite(R2), hmg = min(hmg, abs(R2) - 0.7*D2); end

    % 非球面专项
    if kk ~= 0 || A4 ~= 0 || A6 ~= 0
        rr = linspace(0, SD1, 4001);
        [dz, d2z] = s_deriv(R1,kk,A4,A6,rr);
        slope = atan(max(abs(dz)))*180/pi;
        rev   = any(dz(2:end).*dz(1:end-1) < 0);         % 斜率反号 = 反曲
        sg    = find(d2z(2:end).*d2z(1:end-1) < 0, 1);   % 二阶导变号 = 拐点
        r_inf = NaN; if ~isempty(sg), r_inf = rr(sg); end
    else
        slope = NaN;  rev = false;  r_inf = NaN;
    end

    % BFS：过顶点单参数球，min-max 拟合
    if kk ~= 0 || A4 ~= 0 || A6 ~= 0
        zasp = s_sag(R1,kk,A4,A6,rr);
        sg2  = sign(R1);                                   % 拟合球必须同号，否则会拟合到凸球上
        obj  = @(x) max(abs(zasp - s_sag(sg2*x,0,0,0,rr)));
        xb   = fminbnd(obj, 0.5*abs(R1), 5*abs(R1));
        bfs  = obj(xb);
    else
        bfs = 0;
    end

    flag = '';
    if ~strcmp(nm,'窗口')                              % 平板按 R17 跳过透镜判据
        if ET < 0.5,          flag = [flag 'ET<0.5 ']; end
        if ratio >= 3,        flag = [flag 'CT/ET≥3 ']; end
        if DCT > 6,           flag = [flag 'D/CT>6 ']; end
        if hemis,             flag = [flag '半球 ']; end
        if hmg > 0 && hmg < 0.5, flag = [flag '半球余量<0.5 ']; end
        if rmin < 3,          flag = [flag 'R<3 ']; end
        if rev,               flag = [flag '反曲 ']; end
        if ~isnan(Z) && Z < 0.05, flag = [flag 'Z<0.05 ']; end
        if ~isnan(dr) && dr < 2,  flag = [flag '球心距<2 ']; end
    end

    fprintf('%-6s %4.3f %4.3f %7.2f %6.2f %6.2f %6.2f %5.3f %5.2f %6.2f %5.1f %5.1f %6.4f %s\n', ...
        nm, CT, ET, ratio, DCT, rmin, hmg, Z, 4*Z, dr, slope, r_inf, bfs, flag);
    rows(end+1,:) = [s1 s2 CT ET ratio DCT Z dr slope bfs]; %#ok<SAGROW>
end

%% ---------------- 结论汇总 ----------------
fprintf('\n判定口径：Z>0.15 好做 / 0.05~0.15 一般 / <0.05 困难（Karow 口径 = 4Z）；\n');
fprintf('          球心距建议 >2~3 mm；半球限制 |R| > 0.7·D；非球面 D/CT ≤4（球面 ≤6）。\n\n');

fprintf('非球面 D/CT 复核（比工具 SD/CT 更严）：\n');
for q = [1 6]
    nm = E{q,1}; Dmax = 2*max(E{q,7},E{q,8}); CT = E{q,6};
    fprintf('  %-4s  D/CT = %.2f  %s（非球面限 4）\n', nm, Dmax/CT, tern(Dmax/CT>4,'P1 超限','OK'));
end

%% ---------------- 胶合组：只算「按组才有意义」的项 ----------------
% 组外表面 S6 / S8，两片材质的工艺属性（UV / CTE / 胶层）无法拆开算。
fprintf('\n胶合组（S6–S8，D-LAF50 + H-ZF7LA）—— 只算组级才有意义的项：\n');
Rg1 = 10.3528; Rg2 = 5.6242; CTg = 4.0737 + 2.0390;
DgO = 2*max([5.50 5.00 3.80]);    % 组外圆（未知，按最大通光口径取）
fprintf('  组 Z（统一外圆 Ø%.1f，两端强制同口径）= %.3f  → %s\n', DgO, ...
    0.25*abs(DgO/Rg1 - DgO/Rg2), tern(0.25*abs(DgO/Rg1-DgO/Rg2)>0.15,'好做','一般'));
fprintf('     ↑ 仅作参考：组是刚体，两片各自 Z 才反映单片定心能力（见上表 L3 / L4）\n');
fprintf('  组外表面球心距 = |CT+R2-R1| = %.2f mm（两球心同侧，近同心）\n', abs(CTg+Rg2-Rg1));
fprintf('     → 装配定心不能指望钟罩自定心，须「单片定心磨边 → 胶合 → 定心车削外圆 → 偏心仪分选」\n');
fprintf('  → 其余组级项全为工艺属性：360nm 透过、CTE 匹配、胶层 0.01~0.03mm、胶合定心 20~30″\n');

outCsv = fullfile(rootDir,'zemax-ADAS','ir_cut','data','dfm_IRcut.csv');
fid = fopen(outCsv,'w','n','UTF-8');
fprintf(fid,'element,s1,s2,CT_mm,ET_mm,CT_over_ET,D_over_CT,Z_quarter,Karow_Z,sphere_center_gap_mm,slope_deg,BFS_mm\n');
elab = {'L1','L2','L3','L4','L6','L7','plate'};
for q = 1:nE
    fprintf(fid,'%s,%d,%d,%.4f,%.4f,%.3f,%.2f,%.4f,%.4f,%.4f,%.2f,%.6f\n', elab{q}, ...
        rows(q,1), rows(q,2), rows(q,3), rows(q,4), rows(q,5), rows(q,6), ...
        rows(q,7), 4*rows(q,7), rows(q,8), rows(q,9), rows(q,10));
end
fclose(fid);
fprintf('\nCSV: %s\n', outCsv);
end

%% ================= 工具 =================
function s = s_sag(R,k,A4,A6,r)
    if isinf(R), s = 0; return; end
    c = 1/R;
    disc = 1 - (1+k)*c^2*r.^2;
    if any(disc <= 0), s = NaN; return; end
    s = c*r.^2 ./ (1 + sqrt(disc)) + A4*r.^4 + A6*r.^6;
end

function [dz, d2z] = s_deriv(R,k,A4,A6,r)
    if isinf(R), dz = 0*r; d2z = 0*r; return; end
    c = 1/R;
    disc = 1 - (1+k)*c^2*r.^2;
    sq = sqrt(disc);
    dz  = c*r./sq + 4*A4*r.^3 + 6*A6*r.^5;
    d2z = c./(sq.^3) + 12*A4*r.^2 + 30*A6*r.^4;
end

function out = tern(c,a,b)
    if c, out = a; else, out = b; end
end

function printf_header()
    fprintf('%s\n', repmat('-',1,112));
    fprintf('%-6s %6s %6s %6s %6s %6s %6s %6s %6s %7s %6s %6s %7s %s\n', ...
        '元件','CT','ET','CT/ET','D/CT','min|R|','半球余','Z(¼)','Karow','球心距','max斜','拐点r','BFS','标记');
    fprintf('%s\n', repmat('-',1,112));
end
