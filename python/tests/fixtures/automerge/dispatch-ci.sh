#!/bin/bash
# A fake tools/dispatch-ci.sh: the conclusion from $FAKE/dispatch.<branch>, printed on
# stdout as the real one does; a second line "move <sha>" pushes to the branch meanwhile.
echo "dispatch-ci $*" >> "$FAKE/log"
f="$FAKE/dispatch.${1//\//%}"; c=$(sed -n 1p "$f"); m=$(sed -n 2p "$f")
if [ -n "$m" ]; then
    { grep -v "^origin/$1 " "$FAKE/refs"; echo "origin/$1 ${m#move }"; } > "$FAKE/refs.new"; mv "$FAKE/refs.new" "$FAKE/refs"
fi
echo "$c"; [ "$c" = success ]
