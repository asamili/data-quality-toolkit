"""Widget/session-state key constants for the dashboard UI.

Values must stay stable: they are part of widget identity across reruns and
are referenced by tests.
"""

BIV_COL1 = "biv_col1"
BIV_COL2 = "biv_col2"
BIV_SWAP_BTN = "biv_swap_btn"
BIV_COL1_PREV_BTN = "biv_col1_prev_btn"
BIV_COL1_NEXT_BTN = "biv_col1_next_btn"
BIV_COL2_PREV_BTN = "biv_col2_prev_btn"
BIV_COL2_NEXT_BTN = "biv_col2_next_btn"
BIV_SCATTER_CLIP_AXES = "biv_scatter_clip_axes"
BIV_SCATTER_LOG_SCALE = "biv_scatter_log_scale"
BIV_SCATTER_TREND_LINE = "biv_scatter_trend_line"
BIV_DENSITY_HEATMAP = "biv_density_heatmap"
BIV_CROSSTAB_NORMALIZE = "biv_crosstab_normalize"
BIV_CROSSTAB_HEATMAP = "biv_crosstab_heatmap"
BIV_DT_GRANULARITY = "biv_dt_granularity"
BIV_DT_NUM_AGG = "biv_dt_num_agg"
BIV_DT_CAT_TOP_N = "biv_dt_cat_top_n"

DATASET_CONTEXT = "dataset_context"
DATASET_PATH_INPUT = "dataset_path_input"
DATASET_LARGE_FILE_MODE = "dataset_large_file_mode"
DATASET_ACTIVATE_BTN = "dataset_activate_btn"
DATASET_CLEAR_BTN = "dataset_clear_btn"

EXPORT_CSV_PATH = "export_csv_path"
EXPORT_OUT_DIR = "export_out_dir"
EXPORT_RUN_BTN = "export_run_btn"
# Session-only typed latest-successful-export context (not widget-backed):
# written by the Export page after a confirmed successful run, consumed by the
# Artifact Center "Latest Export" section.
EXPORT_ARTIFACT_CONTEXT = "export_artifact_context"

PIPE_SESSIONS_ROOT = "pipe_sessions_root"
PIPE_EXTRACT = "pipe_extract"
PIPE_TRANSFORM = "pipe_transform"
PIPE_LOAD = "pipe_load"
PIPE_ASSESS = "pipe_assess"
PIPE_MANIFEST = "pipe_manifest"
PIPE_CONFIG_PATH = "pipe_config_path"
PIPE_RUN_BTN = "pipe_run_btn"

# Dry-run workflow step selection (product workflow steps).
PIPE_STEP_LOAD = "pipe_step_load"
PIPE_STEP_PREPROCESS = "pipe_step_preprocess"
PIPE_STEP_QUALITY = "pipe_step_quality"
PIPE_STEP_STATISTICS = "pipe_step_statistics"
PIPE_STEP_DRIFT = "pipe_step_drift"
PIPE_STEP_MANIFEST = "pipe_step_manifest"

# Explicit confirmation gate for the legacy write-capable execution scaffold.
PIPE_CONFIRM_EXEC = "pipe_confirm_exec"

PREP_CSV_PATH = "prep_csv_path"
PREP_RECIPE_STEPS = "prep_recipe_steps"
# Session-only handoff for the most recently confirmed processed version (not
# widget-backed): written by Preprocess Studio after a confirmed lifecycle
# registration, consumed by its own "Set active" action. It is a handoff, never a
# second active pointer — DATASET_CONTEXT remains the one authoritative pointer.
PREP_CONFIRMED_VERSION = "prep_confirmed_version"
PREP_OPERATION = "prep_operation"
PREP_COLUMNS = "prep_columns"
PREP_TARGET_TYPE = "prep_target_type"
PREP_MISSING_STRATEGY = "prep_missing_strategy"
PREP_FILL_VALUE = "prep_fill_value"
PREP_DEDUP_SUBSET = "prep_dedup_subset"
PREP_OUTLIER_STRATEGY = "prep_outlier_strategy"
PREP_ENCODING_STRATEGY = "prep_encoding_strategy"
PREP_SCALING_STRATEGY = "prep_scaling_strategy"
PREP_DERIVED_SOURCE = "prep_derived_source"
PREP_DERIVED_KIND = "prep_derived_kind"
PREP_ADD_STEP_BTN = "prep_add_step_btn"
PREP_CLEAR_RECIPE_BTN = "prep_clear_recipe_btn"
PREP_APPLY_BTN = "prep_apply_btn"

DRIFT_DB_PATH = "drift_db_path"
DRIFT_DATASET_FILTER = "drift_dataset_filter"
DRIFT_LIMIT = "drift_limit"
DRIFT_RATE_THRESHOLD = "drift_rate_threshold"
DRIFT_PSI_THRESHOLD = "drift_psi_threshold"
DRIFT_RUN_SELECTOR = "drift_run_selector"
DRIFT_COLUMN_FILTER = "drift_column_filter"
DRIFT_STATUS_FILTER = "drift_status_filter"
DRIFT_KIND_FILTER = "drift_kind_filter"
DRIFT_METRIC_SORT = "drift_metric_sort"
DRIFT_DISTRIBUTION_COLUMN = "drift_distribution_column"

# EDA Explorer controls.
EDA_CORR_METHOD = "eda_corr_method"
EDA_HIST_AUTO_BINS = "eda_hist_auto_bins"
EDA_CAT_OTHER_BUCKET = "eda_cat_other_bucket"
EDA_DT_GRANULARITY = "eda_dt_granularity"

# Preprocess Studio calculated-column controls.
PREP_CALC_LEFT = "prep_calc_left"
PREP_CALC_RIGHT = "prep_calc_right"
PREP_CALC_ARITH_OP = "prep_calc_arith_op"
PREP_CALC_SCALAR_SRC = "prep_calc_scalar_src"
PREP_CALC_SCALAR_OP = "prep_calc_scalar_op"
PREP_CALC_SCALAR_VALUE = "prep_calc_scalar_value"
PREP_CALC_COND_SRC = "prep_calc_cond_src"
PREP_CALC_COND_CMP = "prep_calc_cond_cmp"
PREP_CALC_COND_VALUE = "prep_calc_cond_value"
PREP_CALC_COND_THEN = "prep_calc_cond_then"
PREP_CALC_COND_ELSE = "prep_calc_cond_else"
PREP_CALC_BIN_SRC = "prep_calc_bin_src"
PREP_CALC_BIN_COUNT = "prep_calc_bin_count"
PREP_CALC_STR_SRC = "prep_calc_str_src"
PREP_CALC_STR_OP = "prep_calc_str_op"
PREP_CALC_STR_FIND = "prep_calc_str_find"
PREP_CALC_STR_REPLACE = "prep_calc_str_replace"
PREP_CALC_STR_OTHER = "prep_calc_str_other"
PREP_CALC_STR_LITERAL = "prep_calc_str_literal"
PREP_CALC_OUTPUT_MODE = "prep_calc_output_mode"
PREP_CALC_OUTPUT_NEW = "prep_calc_output_new"
PREP_CALC_OUTPUT_EXISTING = "prep_calc_output_existing"

# Preprocess Studio recipe step-edit controls.
PREP_EDIT_STEP_SELECT = "prep_edit_step_select"
PREP_REMOVE_STEP_BTN = "prep_remove_step_btn"
PREP_MOVE_UP_BTN = "prep_move_up_btn"
PREP_MOVE_DOWN_BTN = "prep_move_down_btn"

# Export page — Power BI zero-config package controls.
PBI_STAR_DIR = "pbi_star_dir"
PBI_OUT_DIR = "pbi_out_dir"
PBI_BASE_FOLDER = "pbi_base_folder"
PBI_DIM_TIME = "pbi_dim_time"
PBI_CONFIRM = "pbi_confirm"
PBI_GEN_BTN = "pbi_gen_btn"

# Shared cross-page source inputs (Operate/Deliver). One key per concept so a
# value entered on one page persists to others via Streamlit session state.
SRC_WORKSPACE_ROOT = "src_workspace_root"
# Start-page widget key for the Workspace Root input. Kept separate from
# SRC_WORKSPACE_ROOT because Streamlit deletes widget-backed keys when their
# widget is not rendered (i.e., on every other page); the canonical key must
# stay widget-free so it survives navigation and Save-to-Workspace helpers can
# read it anywhere.
SRC_WORKSPACE_ROOT_INPUT = "src_workspace_root_input"
SRC_MONITORING_DB = "src_monitoring_db"
SRC_QUALITY_HISTORY_DB = "src_quality_history_db"
SRC_SESSIONS_ROOT = "src_sessions_root"
# Two distinct run identities. They were one ambiguous ``src_run_id`` key, which
# meant Export's generated run ID and the operator's Sessions Root folder name
# shared one slot: Export could overwrite the folder identity a session workflow
# depended on, and a session lookup could be pointed at a directory that never
# existed. They are separate concepts and now separate keys.
#
# SRC_SESSION_RUN_ID names a workflow session folder under Sessions Root. It is
# operator-entered through the session-run input, consumed by Pipeline Runner and
# by Artifact Center / Manifest Viewer session lookup, and is never written by
# Export.
SRC_SESSION_RUN_ID = "src_session_run_id"
# SRC_EXPORT_RUN_ID identifies the latest successful Export execution. It is
# historical export evidence written only by a successful Export, displayed
# read-only, and must never be used as a Sessions Root folder name.
SRC_EXPORT_RUN_ID = "src_export_run_id"
SRC_DATASET_ID = "src_dataset_id"
SRC_EXPORT_OUT_DIR = "src_export_out_dir"
SRC_PBI_OUT_DIR = "src_pbi_out_dir"

# ---------------------------------------------------------------------------
# Dataset-derived shared session-state (dataset-context contract).
#
# The single documented catalogue of session-state keys whose values are
# *derived from the active dataset* and shared across pages. It is the CONTRACT
# consumed by the atomic transition service
# (``services.dataset_activation``): a genuine dataset binding change clears
# every key listed here. Only keys verified in current repository code are
# listed.
#
#   BIV_COL1, BIV_COL2      -> bivariate column selections
#   EXPORT_CSV_PATH         -> Export page CSV source, auto-seeded from the active
#                              dataset. A switch must not leave the previous
#                              dataset's path behind for the next Export run; the
#                              Export page reseeds it from the newly active
#                              context on its next render.
#   PREP_RECIPE_STEPS       -> Preprocess Studio recipe steps
#   SRC_DATASET_ID          -> shared operator-facing dataset ID
#   PREP_CONFIRMED_VERSION  -> confirmed-version handoff (stale once the dataset
#                              switches, so it is invalidated with the rest)
DATASET_DERIVED_STATE_KEYS: tuple[str, ...] = (
    BIV_COL1,
    BIV_COL2,
    EXPORT_CSV_PATH,
    PREP_RECIPE_STEPS,
    SRC_DATASET_ID,
    PREP_CONFIRMED_VERSION,
)
