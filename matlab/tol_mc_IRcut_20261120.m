%% Q5 公差分析出图（IR-CUT + CG 版，唯一有效口径）
% 输入：zemax-ADAS/layouts/ir_cut/analysis/tol_mc_mtf_q5.txt
%       （Zemax 原始报告，UTF-16LE；判据 DiffMTFAverage @120 lp/mm，采样 2，
%         单测试波长 0.588，9 视场，补偿器 = S12 后焦 ±0.2 mm，500 次 MC）
%       模型：16 面；TDE 60 行只覆盖 S1–S12，窗口板 S13/S14 零公差
% 输出：layouts/ir_cut/TOL_yield_IRcut.png      灵敏度 Top-N + 良率摘要
%       layouts/ir_cut/mc_yield_q5_IRcut.png   蒙特卡洛分布 + 良率—规格曲线
clear; clc; close all;

root = fileparts(fileparts(mfilename('fullpath')));
ana  = fullfile(root, 'zemax-ADAS', 'layouts', 'ir_cut', 'analysis');
outd = fullfile(root, 'zemax-ADAS', 'layouts', 'ir_cut');
src  = fullfile(ana, 'tol_mc_mtf_q5.txt');
assert(isfile(src), '找不到公差报告：%s', src);

spec = 0.35;          % MTF@120 验收下限

L   = read_report(src);
x   = L.trials;
nom = L.nominal;
rss = L.rss_mtf;

n   = numel(x);
mu  = mean(x);  sd = std(x);
cpk = (mu - spec) / (3*sd);
yld = mean(x >= spec);

rng(20261120); B = 2000;
yCI = prctile(mean(x(randi(n, n, B)) >= spec, 1), [2.5 97.5]) * 100;

fprintf('名义 %.5f   预计RSS MTF %.5f\n', nom, rss);
fprintf('N=%d  均值 %.4f  σ %.4f  最差 %.4f\n', n, mu, sd, min(x));
fprintf('良率@%.2f = %.1f%%  (95%%CI %.1f~%.1f%%)  CPK=%.2f\n\n', ...
    spec, 100*yld, yCI(1), yCI(2), cpk);

% ================= 图 1：灵敏度 Top-N（按公差族聚合，去掉 ±X/±Y 重复）=================
T = L.worst;
m = containers.Map('KeyType', 'char', 'ValueType', 'double');
for k = 1:numel(T)
    fam = T(k).type;
    if any(strcmp(fam, {'TEDX', 'TEDY'})), fam = 'TED'; end   % 偏心 X/Y 合成一项
    key = sprintf('%s|%d|%d', fam, T(k).s1, T(k).s2);
    v = abs(T(k).change);
    if isKey(m, key), v = max(v, m(key)); end
    m(key) = v;
end
ks = keys(m); vs = cell2mat(values(m));
[vs, ord] = sort(vs, 'descend'); ks = ks(ord);
nb = min(8, numel(ks));

val = zeros(nb, 1);
lab = cell(nb, 1);
for k = 1:nb
    c = strsplit(ks{k}, '|');
    val(k) = vs(k) / nom * 100;
    lab{k} = item_label(c{1}, str2double(c{2}), str2double(c{3}));
end

fig = figure('Visible', 'off', 'Color', 'w', 'Position', [80 80 1180 520]);
ax  = axes(fig, 'Position', [0.34 0.11 0.60 0.73]); hold(ax, 'on');
barh(ax, 1:nb, val, 0.62, 'FaceColor', [0.32 0.52 0.76], 'EdgeColor', 'none');
set(ax, 'YDir', 'reverse', 'YTick', 1:nb, 'YTickLabel', lab, ...
    'FontSize', 9.5, 'LineWidth', 0.8, 'GridAlpha', 0.15, 'Box', 'off');
xlim(ax, [0, max(val) * 1.18]);
grid(ax, 'on');
for k = 1:nb
    text(ax, val(k) + max(val)*0.015, k, sprintf('−%.1f %%', val(k)), ...
        'FontSize', 9, 'Color', [0.22 0.22 0.22], 'VerticalAlignment', 'middle');
end
xlabel(ax, '单项公差生效后的 MTF@120 跌幅（%，相对名义）');
title(ax, sprintf('名义 %.4f → RSS %.4f（−%.1f %%）　|　蒙特卡洛 500 次均值 %.4f（−%.1f %%）', ...
    nom, rss, 100*(1-rss/nom), mu, 100*(1-mu/nom)), 'FontSize', 10);

sgtitle(sprintf('Q5 公差灵敏度与良率　|　良率 @ MTF≥%.2f = %.1f %%（95 %% CI %.1f~%.1f %%）　CPK = %.2f', ...
    spec, 100*yld, yCI(1), yCI(2), cpk), 'FontSize', 12);
set(findall(fig, '-property', 'FontName'), 'FontName', 'Microsoft YaHei');
set(findall(fig, '-property', 'FontSize'), 'FontSize', 9);
p1 = fullfile(outd, 'TOL_yield_IRcut.png');
exportgraphics(fig, p1, 'Resolution', 300); close(fig);
fprintf('已输出 %s\n', p1);

% ================= 图 2：分布 + 良率—规格曲线 =================
thr = (0.40:0.01:0.58)';
boot = zeros(B, numel(thr));
for b = 1:B
    boot(b, :) = mean(x(randi(n, n, 1)) >= thr', 1);
end
yThr = mean(x >= thr', 1)';
ciLo = prctile(boot, 2.5, 1)';
ciHi = prctile(boot, 97.5, 1)';

fig = figure('Visible', 'off', 'Color', 'w', 'Position', [80 80 1240 500]);

ax1 = subplot(1, 2, 1); hold(ax1, 'on');
p = get(ax1, 'Position'); set(ax1, 'Position', [p(1) + 0.02, p(2), p(3) - 0.02, p(4)]);
histogram(ax1, x, 26, 'Normalization', 'pdf', ...
    'FaceColor', [0.35 0.58 0.80], 'EdgeColor', 'w', 'FaceAlpha', 0.85);
xs = linspace(min(x) - 0.02, max(x) + 0.02, 400);
plot(ax1, xs, normpdf(xs, mu, sd), 'k-', 'LineWidth', 1.6);
yl = ylim(ax1);
xlim(ax1, [min(x) - 0.02, max(x) + 0.02]);
plot(ax1, [spec spec], yl, 'r--', 'LineWidth', 1.8);
plot(ax1, [mu mu], yl, 'k:', 'LineWidth', 1.2);
text(ax1, spec + 0.006, yl(2)*0.06, sprintf('规格 %.2f', spec), 'Color', 'r', 'FontSize', 9);
text(ax1, mu + 0.006, yl(2)*0.80, sprintf('均值 %.4f', mu), 'Color', 'k', 'FontSize', 9);
text(ax1, min(x) + 0.004, yl(2)*0.70, sprintf('最差 %.3f', min(x)), ...
    'Color', [0.55 0.10 0.10], 'FontSize', 9);
xlabel(ax1, 'MTF@120 lp/mm（复色，全视场 T/S 平均）');
ylabel(ax1, '概率密度');
title(ax1, sprintf('蒙特卡洛分布（N=%d）  良率 %.1f%%  CPK=%.2f', n, 100*yld, cpk), 'FontSize', 10);
legend(ax1, {'样本分布', '正态拟合', '验收规格', '样本均值'}, ...
    'Location', 'northwest', 'Box', 'off', 'FontSize', 9);
grid(ax1, 'on'); box(ax1, 'off');

ax2 = subplot(1, 2, 2); hold(ax2, 'on');
fill(ax2, [thr; flipud(thr)], [ciLo; flipud(ciHi)]*100, [0.75 0.85 0.95], ...
    'EdgeColor', 'none', 'FaceAlpha', 0.9);
plot(ax2, thr, yThr*100, '-o', 'Color', [0.10 0.32 0.60], ...
    'MarkerFaceColor', [0.10 0.32 0.60], 'MarkerSize', 4, 'LineWidth', 1.6);
plot(ax2, [spec spec], [0 100], 'r--', 'LineWidth', 1.4);
yline(ax2, 90, ':', 'Color', [0.4 0.4 0.4], 'LineWidth', 1.2);
text(ax2, spec + 0.004, 86, sprintf('规格 %.2f', spec), 'Color', 'r', 'FontSize', 9);
text(ax2, thr(1) + 0.004, 91, '90 % 良率线', 'Color', [0.4 0.4 0.4], 'FontSize', 8);
xlabel(ax2, 'MTF@120 验收下限');
ylabel(ax2, '良率 (%)');
title(ax2, '良率—规格曲线（阴影 = bootstrap 95% CI，B=2000）', 'FontSize', 10);
xlim(ax2, [thr(1) thr(end)]); ylim(ax2, [0 101.5]);
grid(ax2, 'on'); box(ax2, 'off');

for ax = [ax1 ax2]
    q = get(ax, 'Position'); set(ax, 'Position', [q(1), 0.15, q(3), 0.72]);
end
sgtitle(sprintf('Q5 公差蒙特卡洛良率（16 面，CG 固定不计公差，名义 %.3f）', nom), 'FontSize', 12);
set(findall(fig, '-property', 'FontName'), 'FontName', 'Microsoft YaHei');
set(findall(fig, '-property', 'FontSize'), 'FontSize', 9);
set(findall(fig, 'Type', 'axes'), 'LineWidth', 0.8, 'GridAlpha', 0.15);
p2 = fullfile(outd, 'mc_yield_q5_IRcut.png');
exportgraphics(fig, p2, 'Resolution', 300); close(fig);
fprintf('已输出 %s\n', p2);

fprintf('\n--- 良率 vs 规格 ---\n');
for k = 1:numel(thr)
    fprintf('  MTF>=%.2f  %6.2f%%  [%5.2f, %5.2f]\n', thr(k), 100*yThr(k), 100*ciLo(k), 100*ciHi(k));
end

% ================= 局部函数 =================
function L = read_report(fn)
    fid = fopen(fn, 'rb');
    b = fread(fid, inf, 'uint8=>uint8');
    fclose(fid);
    if numel(b) > 2 && b(1) == 255 && b(2) == 254
        b = b(3:end);
    end
    u = uint16(b(1:2:end)) + 256 * uint16(b(2:2:end));
    lines = strtrim(splitlines(string(char(u(:)'))));

    % ---- 名义值 / RSS ----
    nv = regexp(lines, '名义标准\s*:\s*([\d.]+)', 'tokens', 'once');
    iN = find(~cellfun(@isempty, nv), 1, 'first');
    assert(~isempty(iN), '报告里找不到「名义标准」');
    L.nominal = str2double(nv{iN}{1});

    rv = regexp(lines, '^预计 MTF\s*:\s*([\d.]+)', 'tokens', 'once');
    iR = find(~cellfun(@isempty, rv), 1, 'first');
    L.rss_mtf = str2double(rv{iR}{1});

    % ---- 灵敏度全表：每行 6 个数 = 最小侧(值,标准,改变) + 最大侧(值,标准,改变) ----
    iS = find(contains(lines, '灵敏度分析'), 1, 'first');
    assert(~isempty(iS), '报告里找不到「灵敏度分析」段');
    iE = find(contains(lines, '最坏偏离'), 1, 'first');
    if isempty(iE), iE = numel(lines); end
    L.worst = struct('type', {}, 's1', {}, 's2', {}, 'change', {});
    for k = iS:iE
        tok = regexp(lines(k), '\S+', 'match');
        if numel(tok) < 7 || isempty(regexp(tok{1}, '^[A-Z]{4}$', 'once'))
            continue;
        end
        num = str2double(tok(2:end));
        if any(isnan(num)), continue; end
        sn = num(1:end-6);            % 面号：1 个（单面）或 2 个（元件范围）
        if isempty(sn), continue; end
        chg = max(abs(num(end-3)), abs(num(end)));   % 两侧跌幅取大
        L.worst(end+1) = struct('type', tok{1}, 's1', sn(1), ...
            's2', sn(end), 'change', -chg); %#ok<SAGROW>
    end
    assert(~isempty(L.worst), '灵敏度表解析失败');

    % ---- 蒙特卡洛 500 次 ----
    iMC = find(contains(lines, '测试数'), 1, 'first');
    assert(~isempty(iMC), '报告里找不到「蒙特卡罗分析」段');
    L.trials = [];
    for k = iMC:numel(lines)
        tok = regexp(lines(k), '^(\d+)\s+(-?\d+\.\d+)\s+(-?\d+\.\d+)$', 'tokens', 'once');
        if isempty(tok)
            if ~isempty(L.trials) && strlength(lines(k)) > 0, break; end
            continue;
        end
        L.trials(end+1, 1) = str2double(tok{2}); %#ok<SAGROW>
    end
    assert(numel(L.trials) >= 400, '只解析到 %d 个 trial', numel(L.trials));
end

function s = item_label(ty, s1, s2)
    % 本设计的已知项给出工程名称；未列出的按类型 + 面号兜底
    persistent M
    if isempty(M)
        M = containers.Map( ...
            {'TTHI|10|10', 'TTHI|1|1', 'TTHI|3|3', 'TTHI|6|6', 'TTHI|7|7', ...
             'TIND|3|3', 'TED|1|2', 'TED|3|4'}, ...
            {'隔圈 L6→L7（S10）', 'L1 中心厚（S1）', 'L2 中心厚（S3）', ...
             '胶合片厚（S6）', '胶合片厚（S7）', 'L2 折射率（S3）', ...
             'L1 元件偏心（S1–S2）', 'L2 元件偏心（S3–S4）'});
    end
    key = sprintf('%s|%d|%d', ty, s1, s2);
    if isKey(M, key)
        s = M(key);
        return;
    end
    switch ty
        case 'TTHI', base = '厚度';
        case 'TFRN', base = '曲率（光圈）';
        case 'TIRR', base = '不规则度';
        case 'TIND', base = '折射率';
        case 'TABB', base = '阿贝数';
        case 'TED',  base = '元件偏心';
        otherwise,   base = ty;
    end
    if s2 > s1
        s = sprintf('%s　S%d–S%d', base, s1, s2);
    else
        s = sprintf('%s　S%d', base, s1);
    end
end
