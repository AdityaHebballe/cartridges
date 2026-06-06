moduledir = python_dir / 'cartridges'

configure_file(
  input: 'cartridges.in',
  output: 'cartridges',
  configuration: conf,
  install: true,
  install_dir: get_option('bindir'),
)

install_subdir('importer', install_dir: moduledir, exclude_directories: ['__pycache__'])
install_subdir('utils', install_dir: moduledir, exclude_directories: ['__pycache__'])
install_subdir(
  'store',
  install_dir: moduledir,
  exclude_directories: ['__pycache__', 'managers/__pycache__'],
)
install_subdir('logging', install_dir: moduledir, exclude_directories: ['__pycache__'])
install_subdir('errors', install_dir: moduledir, exclude_directories: ['__pycache__'])
install_data(
  [
    'main.py',
    'window.py',
    'preferences.py',
    'details_dialog.py',
    'game.py',
    'game_data.py',
    'game_cover.py',
    'game_sort_filter.py',
    configure_file(input: 'shared.py.in', output: 'shared.py', configuration: conf),
  ],
  install_dir: moduledir,
)
