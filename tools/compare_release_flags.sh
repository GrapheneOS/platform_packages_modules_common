#
# Finds flags that are enabled in one release configuration and then disabled in a
# second release configuration.
#
# This is typically used to find which flags were disabled between the last monthly
# mainline release configuration and the subsequent platform release
# configuration.
#
# This is something that should not happen so we need to verify what
# happened if there are any findings.
#
# This script is intended to be sourced into your shell, not executed directly.
#
# 1. Source this file:
#    $ source compare_release_flags.sh
#
# 2. Run the function with your chosen release configurations:
#    $ compare_release_flags mainline_2025_10 bp4a
#

_record_enabled_flags() {
    local config=$1
    local output_file=$2

    lunch "sdk-${config}-eng" && \
        m all_aconfig_declarations && \
        printflags --filter state:ENABLED --format '[{container}] {fully_qualified_name}' > "${output_file}"
}

compare_release_flags() {
    if [ "$#" -ne 2 ]; then
        echo "Usage: ${FUNCNAME[0]} <mainline_release_config> <platform_release_config>" >&2
        echo "Example: ${FUNCNAME[0]} mainline_2025_10 bp4a" >&2
        return 1
    fi

    if ! type -t gettop >/dev/null || [ -z "$(gettop)" ]; then
        echo "Please run 'source build/envsetup.sh' first." >&2
        return 1
    fi

    local mainline_config=$1
    local platform_config=$2

    local temp_dir
    temp_dir=$(mktemp -d "/tmp/flag_compare.XXXXXXXXXX")

    local mainline_flags_file="${temp_dir}/${mainline_config}-enabled-flags.txt"
    local platform_flags_file="${temp_dir}/${platform_config}-enabled-flags.txt"

    _record_enabled_flags "${mainline_config}" "${mainline_flags_file}" || return 1

    _record_enabled_flags "${platform_config}" "${platform_flags_file}" || return 1

    local diff_output_file="${temp_dir}/mainline_flags_disabled_in_platform.txt"

    diff "${mainline_flags_file}" "${platform_flags_file}" | grep '^<' > "${diff_output_file}"

    if [ -s "${diff_output_file}" ]; then
        echo
        echo "WARNING: Found flags enabled in '${mainline_config}' but NOT in '${platform_config}'."
        echo "The goal is for this list to be empty. Please inspect the file:"
        echo "${diff_output_file}"
        return 1
    else
        echo
        echo "SUCCESS: All flags from '${mainline_config}' are correctly enabled in '${platform_config}'."
        echo "You can inspect the files in '${temp_dir}'"
    fi

    return 0
}
