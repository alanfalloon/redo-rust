redo-ifchange bin/test bin/redo
exec >&2
env -i bin/redo t/all
[ "$(cat t/result)" = "ok" ]
[ -n "$DO_BUILT" ] || echo "Don't forget to test 'minimal/do test'" >&2
