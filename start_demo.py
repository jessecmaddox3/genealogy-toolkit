"""Source-folder launcher: no installation or network access required."""
import argparse
from datetime import datetime
from pathlib import Path
import sys
import uuid
import webbrowser


def main():
    if sys.version_info < (3,12):
        print('Please install Python 3.12 or newer from https://www.python.org/downloads/.',file=sys.stderr)
        return 2
    parser=argparse.ArgumentParser(description='Run the wholly invented genealogy demo.')
    parser.add_argument('--no-open',action='store_true',help='Print the report path without opening a browser')
    args=parser.parse_args()
    root=Path(__file__).resolve().parent
    sys.path.insert(0,str(root/'src'))
    from genealogy.demo import make_demo
    output=root/'output'/('demo-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8])
    try:report=make_demo(output)
    except (OSError,ValueError) as error:
        print('Could not create the demo: '+str(error),file=sys.stderr);return 2
    print('Invented demo created. Open '+str(report))
    if not args.no_open:webbrowser.open(report.as_uri())
    return 0


if __name__=='__main__':raise SystemExit(main())
