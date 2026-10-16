"""Fresh MoveIt -> existing native D baseline; no new obstacle/SDK execution."""
import sys
from run_fixed_depth_native import main

if __name__ == '__main__':
    if '--fresh-moveit-baseline' not in sys.argv:sys.argv.append('--fresh-moveit-baseline')
    main()
