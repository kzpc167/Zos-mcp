# Workspace Instructions

## Zemax / OpticStudio Routing

- For Zemax/OpticStudio zoom-lens tasks only (变焦镜头、zoom lens、variable-focus, or Multi-Configuration Editor/MCE zoom design), load and follow `.github/skills/zemax-zoom-lens-design/SKILL.md` before inspecting or changing the optical design. If the workspace, target folder, or lens-file name contains `Zoom`/`zoom`, treat it as an additional routing signal, but verify the requested file and live OpticStudio system before relying on project records.
- For other Zemax/OpticStudio lens-design tasks, including ADAS, double-Gauss, and camera lenses, load and follow `.github/skills/zemax-ADAS-skill/SKILL.md`. Load its referenced documents **according to the mandatory triggers in SKILL §1**, not "as needed". For report-grade plots, statistics (yield/CPK/CI), curve fitting, or asphere slope/inflection checks, load `zemax-matlab-skill` and actually call the MATLAB MCP — do not silently substitute Python. Do not route these non-zoom tasks to the zoom-lens skill.
- The retired generic skills `zemax-optical-design` and `system-setup-by-type` must not be used or recreated. Their old merit-function ordering, vignetting, MCE, and analysis guidance conflicts with the current ADAS workflow.
- Use the skill's reference model and lab report as prior examples, not as a substitute for validating the current prescription. Keep Zemax-specific procedures in the skill so they are loaded only for relevant work.
