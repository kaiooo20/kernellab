import json

import main


def test_cli_runs_with_custom_parameters(tmp_path, capsys):
    code = main.main(["--quantum", "4", "--frames", "3", "--pages", "7,0,1,2,0,3,0,4",
                      "--no-charts", "--output", str(tmp_path)])
    assert code == 0
    data = json.loads((tmp_path / "resultados.json").read_text(encoding="utf-8"))
    assert data["cpu"]["quantum"] == 4
    assert data["memory"]["frames"] == 3
    assert data["memory"]["references"] == [7, 0, 1, 2, 0, 3, 0, 4]
    assert "RECOMENDAÇÃO" in capsys.readouterr().out
