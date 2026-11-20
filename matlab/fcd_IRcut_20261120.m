% fcd_IRcut_20261120.m
% 加 IR-CUT 版：场曲 + 畸变 验收图（两联图）
% 输入：zemax-ADAS/layouts/analysis/field_curvature_distortion.txt（Zemax 原生导出，UTF-16）
%       列：Y角度 | 子午位移 | 矢高位移 | 实际高度 | 参考高度 | 畸变%
% 输出：zemax-ADAS/layouts/FCD_IRcut.png（300 dpi）
% 口径：3 个波长块 × 101 点；场曲取相对轴上点的位移差；畸变为 Zemax 报告的百分比

root = fileparts(fileparts(mfilename('fullpath')));
src  = fullfile(root, 'zemax-ADAS', 'layouts', 'analysis', 'field_curvature_distortion.txt');
dst  = fullfile(root, 'zemax-ADAS', 'layouts', 'FCD_IRcut.png');
assert(isfile(src), '找不到分析导出文件：%s', src);

fid = fopen(src, 'rb');
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
starts = find(rows(:, 1) == 0);
assert(numel(starts) == 3, '应识别出 3 个波长块');

names  = {'g 0.486 \mum', 'd 0.588 \mum', 'C 0.656 \mum'};
colors = [0.20 0.40 0.85; 0.10 0.60 0.25; 0.85 0.25 0.15];
FCS = 0.05;    % 场曲规格 mm
DIS = 1.0;     % 畸变规格 %

% ---- 读数 ----
curveTan = cell(3,1); curveSag = cell(3,1); curveDis = cell(3,1); th = [];
for k = 1:3
    s = starts(k);
    if k < numel(starts)
        e = starts(k+1) - 1;
    else
        e = size(rows, 1);
    end
    blk = rows(s:e, :);
    th = blk(:, 1);
    curveTan{k} = (blk(:, 2) - blk(1, 2)) * 1000;   % µm，相对轴上
    curveSag{k} = (blk(:, 3) - blk(1, 3)) * 1000;   % µm
    curveDis{k} = blk(:, 6);                        % %
end
fcMax = max(max(abs([curveTan{2}; curveSag{2}])));
dMax  = max(abs(cell2mat(curveDis)));
dP2P  = max(cell2mat(curveDis)) - min(cell2mat(curveDis));
fprintf('场曲（d 线，相对轴上）子午 %.1f µm，弧矢 %.1f µm → 最大 %.4f mm\n', ...
    max(abs(curveTan{2})), max(abs(curveSag{2})), fcMax/1000);
fprintf('畸变 绝对值最大 %.4f %%，峰峰 %.4f %%\n', dMax, dP2P);

% ---- 出图 ----
fig = figure('Visible', 'off', 'Color', 'w', 'Position', [80 80 1240 540]);
set(findall(fig, '-property', 'FontName'), 'FontName', 'Microsoft YaHei');

% 左：场曲
subplot(1, 2, 1);
hold on
hT = plot(th, curveTan{2}, '-',  'Color', colors(2,:), 'LineWidth', 1.8);
hS = plot(th, curveSag{2}, '--', 'Color', colors(2,:), 'LineWidth', 1.4);
yline(FCS*1000,  ':', 'Color', [0.75 0.10 0.10], 'LineWidth', 1.1);
yline(-FCS*1000, ':', 'Color', [0.75 0.10 0.10], 'LineWidth', 1.1);
text(0.4, FCS*1000 - 6, sprintf('规格 ±%.0f µm', FCS*1000), ...
    'Color', [0.75 0.10 0.10], 'FontSize', 8);
xlabel('Y 视场（度）');
ylabel('焦面位移（\mum，相对轴上）');
title(sprintf('场曲（d 0.588 \\mum）：子午 %.1f / 弧矢 %.1f \\mum → %.4f mm', ...
    max(abs(curveTan{2})), max(abs(curveSag{2})), fcMax/1000), 'FontSize', 10);
legend([hT hS], {'子午（T）', '弧矢（S）'}, 'Location', 'southwest', 'FontSize', 9);
xlim([0 18]); ylim([-60 60]);
grid on; box on;
set(gca, 'FontSize', 9, 'LineWidth', 0.8, 'GridAlpha', 0.15);

% 右：畸变
subplot(1, 2, 2);
hold on
hp = gobjects(3,1);
for k = 1:3
    hp(k) = plot(th, curveDis{k}, '-', 'Color', colors(k,:), 'LineWidth', 1.5);
end
yline(DIS,  ':', 'Color', [0.75 0.10 0.10], 'LineWidth', 1.1);
yline(-DIS, ':', 'Color', [0.75 0.10 0.10], 'LineWidth', 1.1);
plot(th, zeros(size(th)), 'k-', 'LineWidth', 0.6);
xlabel('Y 视场（度）');
ylabel('畸变（%）');
title(sprintf('畸变（F-Tan\\theta）：绝对值最大 %.3f %%，峰峰 %.3f %%', dMax, dP2P), 'FontSize', 10);
legend(hp, names, 'Location', 'southwest', 'FontSize', 9);
xlim([0 18]); ylim([-1.1 1.1]);
grid on; box on;
set(gca, 'FontSize', 9, 'LineWidth', 0.8, 'GridAlpha', 0.15);

sgtitle('场曲与畸变验收 —— 加 IR-CUT 版（TOTR 30.0 mm）', 'FontSize', 12);

exportgraphics(fig, dst, 'Resolution', 300);
close(fig);
fprintf('已输出 %s\n', dst);
