import ast
from pathlib import Path


EXPECTED = (
    "Command Center",
    "Performance",
    "SPY / QQQ",
    "Research / Developer Tools",
)
REMOVED = {"Trade Desk", "Opportunities", "Paper Trading", "Strategy Lab", "Advanced"}


def app_tree_and_source():
    source = Path("app.py").read_text(encoding="utf-8")
    return ast.parse(source), source


def production_navigation_value(tree):
    assignment = next(
        node for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "PRODUCTION_NAVIGATION"
                for target in node.targets)
    )
    return ast.literal_eval(assignment.value)


def test_entrypoint_owns_and_renders_exact_production_navigation():
    tree, source = app_tree_and_source()
    navigation = production_navigation_value(tree)

    assert navigation == EXPECTED
    assert REMOVED.isdisjoint(navigation)
    assert "for column, workspace in zip(columns, PRODUCTION_NAVIGATION)" in source
    assert "active_page = render_production_navigation()" in source
    assert "from ui_navigation import" in source
    imported_block = source.split("from ui_navigation import (", 1)[1].split(")", 1)[0]
    assert "navigation" not in imported_block.lower()


def test_production_dispatch_covers_exact_four_destinations():
    _, source = app_tree_and_source()
    main = source.split("def main():", 1)[1]

    assert main.count("active_page ==") == 4
    for page in EXPECTED:
        assert f'active_page == "{page}"' in main
    for page in REMOVED:
        assert f'active_page == "{page}"' not in main
    assert "render_command_center(" in main
    assert "render_performance(" in main
