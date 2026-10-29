"""Package only the approved public listening page and its original demos."""
import argparse
import json
from pathlib import Path
import shutil
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def build(output: Path) -> dict:
    output = output.resolve()
    if output.exists():
        raise ValueError('Choose a new showcase output directory.')
    output.parent.mkdir(parents=True, exist_ok=True)
    files = {'docs/listen/index.html': 'index.html',
             'docs/assets/chiploom-logo.png': 'assets/chiploom-logo.png',
             'docs/listen/media/manifest.json': 'media/manifest.json',
             'docs/listen/media/chiploom-explainer.mp4': 'media/chiploom-explainer.mp4',
             'docs/listen/media/chiploom-explainer.jpg': 'media/chiploom-explainer.jpg'}
    for stem, module in (('pixel_rush', '.mod'), ('voltage_odyssey_v2', '.mod'), ('copper_skies', '.xm')):
        for suffix in (module, '.mp3', '.project.json'):
            files[f'docs/listen/media/{stem}{suffix}'] = f'media/{stem}{suffix}'
    with tempfile.TemporaryDirectory(prefix='.chiploom-site-', dir=output.parent) as temporary:
        stage = Path(temporary) / 'site'
        for source, target in files.items():
            destination = stage / target
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / source, destination)
        (stage / '.nojekyll').touch()
        stage.rename(output)
    return {'ok': True, 'output': str(output), 'files': len(files) + 1}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    print(json.dumps(build(parser.parse_args().output)))
