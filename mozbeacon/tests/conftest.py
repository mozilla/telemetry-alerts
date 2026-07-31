# Phase 3 rewires the ported detection package off Treeherder's imports and replaces
# the test_repository / test_perf_framework / create_push fixtures its tests rely on.
# Until then the files copied into tests/detection/ still import treeherder.* and
# cannot be collected. Drop this line as part of that phase.
collect_ignore = ["detection"]
