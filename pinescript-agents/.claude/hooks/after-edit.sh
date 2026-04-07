#!/bin/bash
# After Edit Hook - Validates Pine Script modifications

FILE_PATH="$1"

# Only process Pine Script files
if [[ "$FILE_PATH" == *.pine ]]; then
    echo "🔍 Pine Script Validation Check"
    
    # Get file content
    if [ -f "$FILE_PATH" ]; then
        FILE_CONTENT=$(cat "$FILE_PATH")
        
        # Check for common Pine Script issues
        
        # Check for repainting risks
        if echo "$FILE_CONTENT" | grep -q "security.*lookahead"; then
            if ! echo "$FILE_CONTENT" | grep -q "lookahead.*=.*barmerge\.lookahead_off"; then
                echo "⚠️ Potential repainting issue detected: security() without lookahead_off"
            fi
        fi
        
        # Check for proper na handling
        if echo "$FILE_CONTENT" | grep -q "\[.*\]"; then
            if ! echo "$FILE_CONTENT" | grep -q "na("; then
                echo "💡 Tip: Consider checking for na values when using historical references []"
            fi
        fi
        
        # Check for strategy risk management
        if echo "$FILE_CONTENT" | grep -q "^strategy("; then
            if ! echo "$FILE_CONTENT" | grep -q "strategy\.risk"; then
                echo "💡 Tip: Consider adding risk management with strategy.risk functions"
            fi
        fi
        
        # Check for proper input groups
        if echo "$FILE_CONTENT" | grep -q "input\." && ! echo "$FILE_CONTENT" | grep -q "group="; then
            echo "💡 Tip: Consider organizing inputs with group= parameter for better UX"
        fi

        # Check for line continuation issues - common patterns that cause errors
        # Look for lines ending with ? or : that are part of ternary operators
        # followed by lines at the same or lower indentation level
        LINE_NUM=0
        PREV_LINE=""
        PREV_INDENT=0
        while IFS= read -r LINE; do
            LINE_NUM=$((LINE_NUM + 1))
            # Calculate current line indentation (count leading spaces/tabs)
            STRIPPED="${LINE#"${LINE%%[![:space:]]*}"}"
            CURR_INDENT=$((${#LINE} - ${#STRIPPED}))

            # Check if previous line ends with ternary operator parts (? or :) not inside strings
            # and current line is not more indented
            if echo "$PREV_LINE" | grep -qE '[^"'\'':]:[[:space:]]*$|[^"'\''?]\?[[:space:]]*$'; then
                if [ "$CURR_INDENT" -le "$PREV_INDENT" ] && [ -n "$STRIPPED" ]; then
                    echo "⚠️ Line $LINE_NUM: Possible line continuation error - continuation must be indented MORE than line $((LINE_NUM - 1))"
                    echo "   See: docs/pinescript-v6/quick-reference/syntax-basics.md for line wrapping rules"
                fi
            fi

            PREV_LINE="$LINE"
            PREV_INDENT="$CURR_INDENT"
        done < "$FILE_PATH"

        echo "✅ Pine Script validation complete"
    fi
fi

exit 0