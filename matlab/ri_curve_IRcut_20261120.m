% ri_curve_IRcut_20261120.m
% 加 IR-CUT 版（TOTR 30.0）相对照度曲线，报告级重绘
% 输入：zemax-ADAS/layouts/ir_cut/analysis/relative_illumination.txt（Zemax 原生 Relative Illumination 导出，UTF-16）
% 输出：zemax-ADAS/layouts/ir_cut/RI_curve_IRcut.png（300 dpi）
% 口径：横轴 Y 视场角；左轴 Rel. Ill（轴上=1）；右轴 F/# 效率；红色虚线 = 60 % 规格

root = fileparts(fileparts(mfilename('fullpath')));
src  = fullfile(root, 'zemax-ADAS', 'layouts', 'ir_cut', 'analysis', 'relative_illumination.txt');
dst  = fullfile(root, 'zemax-ADAS', 'layouts', 'ir_cut', 'RI_curve_IRcut.png');
assert(isfile(src), '找不到分析导出文件：%s', src);

% ---- 读 UTF-16LE（带 BOM），只取数值 ----
fid = fopen(src, 'rb');
b = fread(fid, inf, 'uint8=>uint8');
fclose(fid);
if numel(b) > 2 && b(1) == 255 && b(2) == 254
    b = b(3:end);
end
u = uint16(b(1:2:end)) + 256 * uint16(b(2:2:end));
lines = splitlines(string(char(u(:)')));

vals = [];
for k = 1:numel(lines)
    n = str2double(regexp(lines(k), '-?\d+\.\d+', 'match'));
    if numel(n) == 3
        vals(end+1, :) = n; %#ok<SAGROW>
    end
end
assert(size(vals, 1) == 21, '应解析出 21 个视场点，实际 %d 行', size(vals, 1));

f   = vals(:, 1);
ril = vals(:, 2);
fno = vals(:, 3);

assert(abs(ril(1) - 1.0) < 1e-6, '轴上相对照度应为 1.000');
assert(abs(f(end) - 17.42699056) < 1e-4, '最大视场应为 17.427 度');
fprintf('视场点 %d 个，范围 %.3f–%.3f 度\n', height(vals), f(1), f(end));
fprintf('Rel.Ill  最小 %.5f @ %.3f 度\n', min(ril), f(ril == min(ril)));
fprintf('F/# 效率 范围 %.5f–%.5f\n', min(fno), max(fno));
key = [1, 11, 19, 21];
fprintf('%8s %10s %12s\n', 'field', 'Rel.Ill', 'F/#eff');
for k = key
    fprintf('%8.3f %10.4f %12.4f\n', f(k), ril(k), fno(k));
end

% ---- 出图 ----
fig = figure('Visible', 'off', 'Color', 'w', 'Position', [100 100 900 560]);
set(findall(fig, '-property', 'FontName'), 'FontName', 'Microsoft YaHei');

yyaxis left
p1 = plot(f, ril, '-o', 'LineWidth', 1.5, 'MarkerSize', 5, ...
    'Color', [0.00 0.35 0.75], 'MarkerFaceColor', [0.00 0.35 0.75]);
hold on
yline(0.60, '--', 'Color', [0.80 0.10 0.10], 'LineWidth', 1.2);
text(0.3, 0.615, '规格 60 %（左轴）', 'Color', [0.80 0.10 0.10], 'FontSize', 9);
ylim([0.50 1.05]);
ylabel('相对照度');
yticks(0.5:0.1:1.0);

% 左轴标注必须写在 yyaxis left 段内（切右轴后 text 用右轴坐标系）
for k = [11, 19, 21]
    text(f(k), ril(k) + 0.018, sprintf('%.4f', ril(k)), ...
        'HorizontalAlignment', 'center', 'FontSize', 8, 'Color', [0.00 0.25 0.55]);
end

yyaxis right
p2 = plot(f, fno, '--s', 'LineWidth', 1.2, 'MarkerSize', 4, ...
    'Color', [0.85 0.45 0.00], 'MarkerFaceColor', 'w');
ylabel('F/# 效率（有效 F/#）');
ylim([1.44 1.61]);

xlabel('Y 视场（度）');
xlim([0 18]);
xticks(0:2:18);
grid on
box on
set(gca, 'FontSize', 9, 'LineWidth', 0.8, 'GridAlpha', 0.15);

title({'相对照度 vs 视场（0.588 \mum）—— 加 IR-CUT 版（TOTR 30.0 mm）', ...
       sprintf('边缘 17.43{\\circ}：%.4f，较 60%% 规格余量 %.1f 个百分点', ...
               ril(end), (ril(end) - 0.60) * 100)}, 'FontSize', 11);

legend([p1 p2], {'相对照度（左轴）', 'F/# 效率（右轴）'}, 'Location', 'southwest', 'FontSize', 9);

exportgraphics(fig, dst, 'Resolution', 300);
close(fig);
fprintf('已输出 %s\n', dst);
