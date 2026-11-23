function power_IRcut_20261121()
%% 逐片光焦度（IR-CUT 版，d 线 0.588 µm）
% 处方由 ZOS-API get_system_info 读回（2026-11-21 实测），与 15mmF1.4 定心系数_IRcut_20261120.zos 一致
% 厚透镜：Φ = φ1 + φ2 − (t/n)·φ1·φ2，φ1 = (n−1)/R1，φ2 = (1−n)/R2
% 非球面用顶点曲率半径（一阶量只由顶点 R 决定，A4/A6 不影响光焦度）
% 输出：控制台表 + zemax-ADAS/ir_cut/data/power_IRcut_20261121.csv
clc; close all;
rootDir = fileparts(fileparts(mfilename('fullpath')));

%% ---------------- 元件表 ----------------
% name  R1        R2         CT        n_d      glass
E = {
 'L1'    34.78036051606992   17.435718549658848   3.307824716548504  1.58144  'H-QF50A'
 'L2'    20.530294107490068 -28.595593345652322   4.0797171225286855 1.77288  'D-LAF50-25'
 'L3'    10.352808109044268 -38.17719639780744    4.073732764136589  1.77400  'D-LAF50'
 'L4'   -38.17719639780744    5.624211470379923   2.039046734811184  1.80518  'H-ZF7LA'
 'L6'    14.034021134058413 -12.052375463335132   4.288669457140633  1.77288  'D-LAF50-25'
 'L7'    -6.407646360638522  Inf                  1.3510440336689604 1.48749  'H-QK3L'
};
nE = size(E,1);

EFL_SYS = 15.004573;                     % Zemax 一阶 EFFL（mm）
PHI_SYS = 1000/EFL_SYS;                  % 系统光焦度，屈光度

fprintf('%s\n', repmat('-',1,104));
fprintf('%-4s %-11s %9s %9s %9s %9s %9s %9s\n', ...
    '元件','玻璃','φ1(D)','φ2(D)','Φ(D)','f''(mm)','BFL(mm)','占比');
fprintf('%s\n', repmat('-',1,104));

P = zeros(nE,7);  % [phi1 phi2 phi f bfl R1 R2]  内部单位 mm^-1
for q = 1:nE
    nm = E{q,1};  R1 = E{q,2};  R2 = E{q,3};  t = E{q,4};  n = E{q,5};
    phi1 = (n-1)/R1;
    phi2 = 0; if isfinite(R2), phi2 = (1-n)/R2; end
    Phi  = phi1 + phi2 - (t/n)*phi1*phi2;         % mm^-1（厚透镜）
    f    = 1/Phi;
    bfl  = (1 - (t/n)*phi1)/Phi;                  % 后顶点到焦点
    % ---- ABCD 复核（y=1 平行入射，v=n·u）----
    M1 = [1 0; -phi1 1];  Tt = [1 t/n; 0 1];  M2 = [1 0; -phi2 1];
    M  = M2*Tt*M1;  y2 = M(1,1);  v2 = M(2,1);
    f_abcd   = -1/v2;
    bfl_abcd = -y2/v2;
    assert(abs(f_abcd-f) < 1e-9 && abs(bfl_abcd-bfl) < 1e-9, 'ABCD 复核不一致：%s', nm);

    P(q,:) = [phi1 phi2 Phi f bfl R1 R2];
    fprintf('%-4s %-11s %9.2f %9.2f %9.2f %9.3f %9.3f %8.1f%%\n', ...
        nm, E{q,6}, 1000*phi1, 1000*phi2, 1000*Phi, f, bfl, ...
        100*1000*Phi/PHI_SYS);
end
fprintf('%s\n', repmat('-',1,104));

sumPhi = 1000*sum(P(:,3));
fprintf('\n系统：EFFL = %.4f mm → Φ_sys = %.2f D\n', EFL_SYS, PHI_SYS);
fprintf('逐片代数和：ΣΦ = %+.2f D（= %.2f × Φ_sys）\n', sumPhi, sumPhi/PHI_SYS);
fprintf('Σ|Φ| = %.2f D\n', 1000*sum(abs(P(:,3))));

%% ---------------- 元件代数和（不等于系统光焦度）----------------
fprintf('\n逐片（各自单独置于空气中）代数和：%+.2f D\n', 1000*sum(P(:,3)));
fprintf('  ↑ 这只是"如果六片都摊开在空气里"的和，含胶合面与间隔后完全不同，见下\n');

%% ---------------- 全系统 ABCD 复核 ----------------
% 逐面矩阵相乘，确认这套处方与逐片分解自洽：f' 应等于 Zemax 的 15.0046 mm
S = [ 34.78036051606992   3.307824716548504  1.58144
      17.435718549658848  4.0                1.0
      20.530294107490068  4.0797171225286855 1.77288
     -28.595593345652322  0.47               1.0
      Inf                 0.49               1.0
      10.352808109044268  4.073732764136589  1.77400
     -38.17719639780744   2.039046734811184  1.80518
       5.624211470379923  3.8                1.0
      14.034021134058413  4.288669457140633  1.77288
     -12.052375463335132  1.0                1.0
      -6.407646360638522  1.3510440336689604 1.48749
      Inf                 0.7                1.0
      Inf                 0.4                1.5168
      Inf                 0.0                1.0 ];
M = eye(2);  nPrev = 1;
for k = 1:size(S,1)
    nNow = S(k,3);
    ph   = 0; if isfinite(S(k,1)), ph = (nNow-nPrev)/S(k,1); end
    M    = [1 0; -ph 1]*M;
    if k < size(S,1), M = [1 S(k,2)/nNow; 0 1]*M; end
    nPrev = nNow;
end
f_sys = -1/M(2,1);
fprintf('\n全系统 ABCD：f'' = %.4f mm（Zemax %.4f，差 %+.1f µm）\n', ...
    f_sys, EFL_SYS, 1000*(f_sys-EFL_SYS));
assert(abs(f_sys-EFL_SYS) < 0.005, '全系统 ABCD 与 Zemax 不符，处方或面序有问题');

%% ---------------- 组合后的实际光焦度（含间隔 / 胶合面）----------------
% 胶合面 S7 两侧是玻璃—玻璃，界面光焦度只有 (1.80518−1.774)/(−38.177) = −0.8 D，
% 所以"L3 + L4"两片单独在空气中的光焦度之和（−76 D）没有物理意义，必须按实际介质算。
G = { '前组   S1–S4 (L1+L2)', 1,  4
      '胶合组 S6–S8 (L3+L4)', 6,  8
      '后组   S9–S12 (L6+L7)', 9, 12
      '全系统 S1–S14',         1, 14 };
fprintf('\n按实际介质（含空气间隔与胶合面）的组合光焦度：\n');
for g = 1:size(G,1)
    [fg, bg, Pg] = abcd_group(S, G{g,2}, G{g,3});
    fprintf('  %-22s Φ = %+7.2f D   f'' = %+8.3f mm   BFL = %+8.3f mm\n', ...
        G{g,1}, 1000*Pg, fg, bg);
end
% 胶合面对比：拆开（各自在空气中）vs 原位
p3 = 1000*P(3,3);  p4 = 1000*P(4,3);
fprintf('\n胶合组读法：\n');
fprintf('  拆开算（各自在空气中）L3 %+.2f D + L4 %+.2f D = %+.2f D  ← 不是组的光焦度\n', ...
    p3, p4, p3+p4);
[~, ~, Pg_in] = abcd_group(S,6,8);
fprintf('  原 位（S6→S8 完整追迹）          = %+.2f D  ← 这才是这一组的实际光焦度\n', 1000*Pg_in);
fprintf('  差异来源：S7 是玻璃—玻璃界面，φ = (1.80518−1.774)/(−38.177) = %+.2f D，几乎不折光\n', ...
    1000*(1.80518-1.774)/(-38.17719639780744));

%% ---------------- CSV ----------------
outCsv = fullfile(rootDir,'zemax-ADAS','ir_cut','data','power_IRcut_20261121.csv');
fid = fopen(outCsv,'w','n','UTF-8');
fprintf(fid,'element,glass,R1_mm,R2_mm,CT_mm,nd,phi1_D,phi2_D,phi_D,efl_mm,bfl_mm,share_of_system\n');
for q = 1:nE
    fprintf(fid,'%s,%s,%.6f,%s,%.6f,%.5f,%.4f,%.4f,%.4f,%.4f,%.4f,%.4f\n', ...
        E{q,1}, E{q,6}, P(q,6), tern_str(P(q,7)), E{q,4}, E{q,5}, ...
        1000*P(q,1), 1000*P(q,2), 1000*P(q,3), P(q,4), P(q,5), ...
        1000*P(q,3)/PHI_SYS);
end
fclose(fid);
fprintf('\nCSV: %s\n', outCsv);
end

function s = tern_str(v)
    if isinf(v), s = 'Inf'; else, s = sprintf('%.6f', v); end
end

function [f, bfl, Phi] = abcd_group(S, k1, k2)
% 组前介质为空气；按真实介质逐面折射 + 间隔传播，返回组的光焦度与后焦距
    nPrev = 1;  M = eye(2);
    for k = k1:k2
        nNow = S(k,3);
        ph = 0;  if isfinite(S(k,1)), ph = (nNow-nPrev)/S(k,1); end
        M = [1 0; -ph 1]*M;
        if k < k2, M = [1 S(k,2)/nNow; 0 1]*M; end
        nPrev = nNow;
    end
    Phi = -M(2,1);
    f   = -1/M(2,1);
    bfl = -M(1,1)/M(2,1);
end
