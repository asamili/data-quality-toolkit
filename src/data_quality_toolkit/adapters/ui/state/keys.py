"""Widget/session-state key constants for the dashboard UI.

Values must stay stable: they are part of widget identity across reruns and
are referenced by tests.
"""

BIV_COL1 = "biv_col1"
BIV_COL2 = "biv_col2"

DATASET_CONTEXT = "dataset_context"
DATASET_PATH_INPUT = "dataset_path_input"
DATASET_LARGE_FILE_MODE = "dataset_large_file_mode"
DATASET_ACTIVATE_BTN = "dataset_activate_btn"
DATASET_CLEAR_BTN = "dataset_clear_btn"

EXPORT_CSV_PATH = "export_csv_path"
EXPORT_OUT_DIR = "export_out_dir"
EXPORT_RUN_BTN = "export_run_btn"

PIPE_RUN_ID = "pipe_run_id"
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
