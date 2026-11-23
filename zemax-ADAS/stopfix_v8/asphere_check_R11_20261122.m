% asphere_check_R11_20261122.m
% 长后焦 v8 · 末片半球专项：两片偶次非球面（S1 / S11）面型校核
%   矢高 z(r)、一阶导 dz/dr（反曲）、二阶导 d2z/dr2（拐点）、边缘斜率角、最佳拟合球偏离 BFS
% 输出：figs/asphere_S1.png、figs/asphere_S11.png

clear; close all;

base = fileparts(mfilename('fullpath'));
if isempty(base); base = pwd; end
figdir = fullfile(base,'figs');
if ~exist(figdir,'dir'); mkdir(figdir); end

% ---- 面参数（取自 LDE 终态）----
S(1).name = 'S1  L1 (H-KF6)';
S(1).tag  = 'S1';
S(1).R    = 34.61487597343554;
S(1).sd   = 8.0;
S(1).A4   = -8.260640534361943e-05;
S(1).A6   = -2.653636337350019e-07;

S(2).name = 'S11 L7 (H-QK3L)';
S(2).tag  = 'S11';
S(2).R    = -7.1;
S(2).sd   = 5.0;
S(2).A4   =  0.0004669666648233396;
S(2).A6   =  3.716361192294265e-06;

K = -1;

fprintf('=== 非球面面型校核 (k = -1, 仅 A4/A6) ===\n');
for i = 1:numel(S)
    c  = 1/S(i).R;   sd = S(i).sd;
    r  = linspace(0,sd,4001)';
    z  = sag(r,c,K,S(i).A4,S(i).A6);
    dz = dzdr(r,c,K,S(i).A4,S(i).A6);
    d2 = d2zdr2(r,c,K,S(i).A4,S(i).A6);

    rev = find(sign(dz(2:end)).*sign(dz(1:end-1)) < 0, 1);
    if isempty(rev); rev_txt='无'; else; rev_txt=sprintf('r = %.3f mm', r(rev)); end
    infl = find(sign(d2(2:end)).*sign(d2(1:end-1)) < 0, 1);
    if isempty(infl); infl_txt='无'; else; infl_txt=sprintf('r = %.3f mm', r(infl)); end

    slope = atand(dz(end));
    Rbfs  = fit_sphere(z,r);
    dev   = max(abs(z - sag(r,1/Rbfs,0,0,0)));

    fprintf('\n%s\n', S(i).name);
    fprintf('  R = %.4f  SD = %.2f  A4 = %+.5e  A6 = %+.5e\n', S(i).R, sd, S(i).A4, S(i).A6);
    fprintf('  矢高 z(0)=%.4f  z(边缘)=%.4f mm   sag/D = %.4f\n', z(1), z(end), abs(z(end))/(2*sd));
    fprintf('  边缘斜率 dz/dr = %+.4f -> %.2f deg\n', dz(end), slope);
    fprintf('  反曲：%s   拐点：%s\n', rev_txt, infl_txt);
    fprintf('  最佳拟合球 R_BFS = %.4f mm，非球面度 = %.4f mm (%.1f 波 @0.588um, 双程)\n', ...
            Rbfs, dev, 2*dev/0.588e-3);
    if ~isempty(infl)
        fprintf('  拐点→通光边缘余量 = %.3f mm (%.1f%% of SD)\n', sd - r(infl), 100*(sd - r(infl))/sd);
    end

    if slope > 45
        fprintf('  >> 边缘斜率 %.1f deg > 45 deg：不可加工\n', slope);
    elseif slope > 30
        fprintf('  >> 边缘斜率 %.1f deg > 30 deg：标关注\n', slope);
    else
        fprintf('  >> 边缘斜率 %.1f deg <= 30 deg：OK\n', slope);
    end
    if isempty(rev); fprintf('  >> 无反曲：合格\n'); else; fprintf('  >> 存在反曲：不合格\n'); end

    fig = figure('Color','w','Position',[80 80 820 600],'Visible','off');
    subplot(2,1,1); hold on; box on; grid on;
    plot(r,z,'-','LineWidth',1.6,'Color',[0 0.45 0.74]);
    plot(r,sag(r,1/Rbfs,0,0,0),'--','LineWidth',1.0,'Color',[0.85 0.33 0.10]);
    ylabel('矢高 z (mm)');
    legend({'非球面','最佳拟合球'},'Location','best','Box','off');
    title(sprintf('%s  R = %.3f mm, SD = %.1f mm', S(i).name, S(i).R, sd),'FontSize',11);
    subplot(2,1,2); hold on; box on; grid on;
    yyaxis left;  plot(r,dz,'-','LineWidth',1.4);  ylabel('dz/dr');
    yyaxis right; plot(r,d2,'--','LineWidth',1.2); ylabel('d^2z/dr^2');
    xlabel('通光半径 r (mm)');
    set(findall(fig,'-property','FontName'),'FontName','Microsoft YaHei');
    fn = fullfile(figdir, sprintf('asphere_%s.png', S(i).tag));
    exportgraphics(fig, fn, 'Resolution', 300); close(fig);
    fprintf('  图：%s\n', fn);
end

% ---------- 局部函数 ----------
function z = sag(r,c,K,A4,A6)
    z = c*r.^2 ./ (1 + sqrt(1 - (1+K)*c^2*r.^2)) + A4*r.^4 + A6*r.^6;
end
function d = dzdr(r,c,K,A4,A6)
    s = sqrt(1 - (1+K)*c^2*r.^2);
    d = c*r./s + 4*A4*r.^3 + 6*A6*r.^5;
end
function d2 = d2zdr2(r,c,K,A4,A6)
    s = sqrt(1 - (1+K)*c^2*r.^2);
    d2 = c./(s.^3) + 12*A4*r.^2 + 30*A6*r.^4;
end
function R = fit_sphere(z,r)
    R0 = r(end)^2/(2*z(end));
    lo = min([R0*0.5 R0*2]);  hi = max([R0*0.5 R0*2]);
    f  = @(x) sum((z - sag(r,1/x,0,0,0)).^2);
    R  = fminbnd(f, lo, hi);
end
