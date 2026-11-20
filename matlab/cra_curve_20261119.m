% cra_curve_20261119.m
% CRA（主光线角）vs 像高，三波长叠加，标注峰值与客户限值
% 数据：matlab/data/cra_vs_field_20261119.csv（由临时 RAID 操作数逐视场读取，读完已删除）
% 像高：由 layouts/no_ir_cut/analysis/field_curvature_distortion.txt 的 d 线「实际高度」插值得到
% 输出：layouts/no_ir_cut/CRA_curve.png（300 dpi）

root = fileparts(fileparts(mfilename('fullpath')));
csvp = fullfile(root, 'matlab', 'data', 'cra_vs_field_20261119.csv');
fcp  = fullfile(root, 'zemax-ADAS', 'layouts', 'no_ir_cut', 'analysis', 'field_curvature_distortion.txt');
dst  = fullfile(root, 'zemax-ADAS', 'layouts', 'no_ir_cut', 'CRA_curve.png');
CRA_SPEC = 18.0;                     % 客户限值（沿用本项目规格表，换客户改这一行）
F_MAX    = 17.42699056;              % 最大视场角（度）

% ---- 1. CRA 数据 ----
M = readmatrix(csvp, 'NumHeaderLines', 1);
theta = M(:, 2);   cra_g = M(:, 3);   cra_d = M(:, 4);   cra_c = M(:, 5);
assert(numel(theta) == 10, 'CRA 数据应为 10 个视场点');

% ---- 2. 像高：解析场曲导出，取 d 线块的实际高度 ----
fid = fopen(fcp, 'rb');
b = fread(fid, inf, 'uint8=>uint8');
fclose(fid);
if numel(b) > 2 && b(1) == 255 && b(2) == 254
    b = b(3:end);
end
u = uint16(b(1:2:end)) + 256 * uint16(b(2:2:end));
lines = splitlines(string(char(u(:)')));
rows = [];
for k = 1:numel(lines)
    n = str2double(regexp(lines(k), '-?\d+\.\d+', 'match'));
    if numel(n) == 6
        rows(end+1, :) = n; %#ok<SAGROW>
    end
end
assert(size(rows, 1) == 303, '场曲表应为 303 行，实际 %d', size(rows, 1));
starts = find(rows(:, 1) == 0);              % 每个波长块的第一行视场角为 0
assert(numel(starts) == 3, '应识别出 3 个波长块');
blk = rows(starts(2):starts(3)-1, :);        % 第 2 块 = 0.588 µm
assert(abs(blk(end, 1) - F_MAX) < 1e-6, 'd 线块末端应为最大视场');
yh = interp1(blk(:, 1), blk(:, 4), theta, 'linear', 'extrap');   % 实际像高 (mm)
assert(all(diff(yh) > 0), '像高应随视场单调增加');

% ---- 3. 关键量 ----
[peak, ip] = max([cra_g, cra_d, cra_c], [], 'all');
[i_r, i_c] = ind2sub([10, 3], ip);
labels = {'g 0.486 \mum', 'd 0.588 \mum', 'C 0.656 \mum'};
fprintf('%8s %10s %10s %10s %10s\n', 'H', 'field', 'y_img', 'g', 'd');
for k = 1:10
    fprintf('%8.3f %10.3f %10.4f %10.3f %10.3f\n', M(k, 1), theta(k), yh(k), cra_g(k), cra_d(k));
end
fprintf('峰值 %.4f 度：%s，视场 %.2f 度，像高 %.4f mm\n', peak, labels{i_c}, theta(i_r), yh(i_r));
fprintf('边缘(17.43 度)：g %.3f / d %.3f / C %.3f 度\n', cra_g(end), cra_d(end), cra_c(end));

% ---- 4. 出图 ----
fig = figure('Visible', 'off', 'Color', 'w', 'Position', [100 100 900 560]);
set(findall(fig, '-property', 'FontName'), 'FontName', 'Microsoft YaHei');
hold on
p1 = plot(yh, cra_g, '-o', 'Color', [0.20 0.40 0.85], 'LineWidth', 1.4, 'MarkerSize', 4);
p3 = plot(yh, cra_d, '-s', 'Color', [0.10 0.60 0.25], 'LineWidth', 1.6, 'MarkerSize', 5);
p2 = plot(yh, cra_c, '-^', 'Color', [0.85 0.25 0.15], 'LineWidth', 1.4, 'MarkerSize', 5);

hspec = yline(CRA_SPEC, '--', 'Color', [0.75 0.10 0.10], 'LineWidth', 1.2);
text(yh(1) + 0.05, CRA_SPEC + 0.45, sprintf('客户限值 %.0f°', CRA_SPEC), ...
    'Color', [0.75 0.10 0.10], 'FontSize', 9);

plot(yh(i_r), peak, 'kd', 'MarkerSize', 9, 'MarkerFaceColor', 'k');
text(yh(i_r) - 0.05, peak + 1.3, sprintf('峰值 %.2f°（%s，视场 %.1f°）', peak, labels{i_c}, theta(i_r)), ...
    'HorizontalAlignment', 'right', 'FontSize', 9);

text(yh(end) - 0.05, cra_d(end) - 1.5, sprintf('边缘 %.2f°（d）', cra_d(end)), ...
    'HorizontalAlignment', 'right', 'FontSize', 9, 'Color', [0.10 0.45 0.20]);

xlim([0 4.85]);
ylim([0 CRA_SPEC + 2]);
xlabel('像高（mm）');
ylabel('CRA（度）');
grid on
box on
set(gca, 'FontSize', 9, 'LineWidth', 0.8, 'GridAlpha', 0.15);
title({sprintf('CRA vs 像高（三波长，25 {\\circ}C，全视场 %.2f{\\circ}）', F_MAX), ...
       sprintf('峰值 %.2f{\\circ} 出现在 %.0f%% 视场；边缘回落至 %.2f{\\circ}，距限值 %.0f{\\circ} 余量 %.1f{\\circ}', ...
               peak, M(i_r, 1) * 100, cra_d(end), CRA_SPEC, CRA_SPEC - peak)}, 'FontSize', 10);
legend([p1 p3 p2], labels, 'Location', 'southeast', 'FontSize', 9);

exportgraphics(fig, dst, 'Resolution', 300);
close(fig);
fprintf('已输出 %s\n', dst);
