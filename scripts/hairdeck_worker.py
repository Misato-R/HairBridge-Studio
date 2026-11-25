"""Run the existing local HairDeck model; no model weights are bundled here."""
import json
import shutil
import sys
import traceback
from pathlib import Path

job = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
out = Path(job["output"])
try:
    sys.path.insert(0, job["hairdeckRoot"])
    from hairdeck.infer.image import Pipeline
    print("Loading local HairDeck model", flush=True)
    pipeline = Pipeline(chains=False)
    result = pipeline.run(job["reference"], seed=job["seed"], steps=50, cfg=2.0,
                          n_samples=1, chains=False, out_dir=str(out / "inference"))
    if not result["ok"]:
        raise RuntimeError(result["message"])
    cards = out / "inference" / f"cards_seed{job['seed']}.json"
    shutil.copyfile(cards, out / "cards.json")
    preview = out / "inference" / f"hair_seed{job['seed']}.glb"
    if preview.exists():
        shutil.copyfile(preview, out / "preview.glb")
    report = {"success": True, "seed": job["seed"], "cards": len(json.loads(cards.read_bytes())),
              "notes": result.get("notes"), "timings": result.get("timings")}
except Exception as exc:
    report = {"success": False, "error": str(exc), "traceback": traceback.format_exc()}
    raise
finally:
    (out / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
