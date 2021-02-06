#!/bin/bash -ex

SOURCE_TREE=$1
DESTINATION_TREE=$2
API_LEVEL=$3
SOURCE_TREE_TYPE=$(test -e ${DESTINATION_TREE}/vendor/unbundled_google/modules && echo GOOGLE || echo PARTNER)

function sdk_lib_bp() {
    modulename=$1
    apexname=$2
    shared_library=$(test \( "$apexname" == com.android.ipsec \) -a \( "$API_LEVEL" -lt 31 \) && echo true || echo false)
    cat << EOF
java_sdk_library_import {
    name: "${modulename}",
    owner: "google",
    prefer: true,
    shared_library: ${shared_library},
    apex_available: [
        "${apexname}",
        "test_${apexname}",
    ],
    public: {
        jars: ["sdk_library/public/${modulename}.jar"],
        current_api: "sdk_library/public/${modulename}.txt",
        removed_api: "sdk_library/public/${modulename}-removed.txt",
        sdk_version: "module_current",
    },
    system: {
        jars: ["sdk_library/system/${modulename}.jar"],
        current_api: "sdk_library/system/${modulename}.txt",
        removed_api: "sdk_library/system/${modulename}-removed.txt",
        sdk_version: "module_current",
    },
    module_lib: {
        jars: ["sdk_library/module_lib/${modulename}.jar"],
        current_api: "sdk_library/module_lib/${modulename}.txt",
        removed_api: "sdk_library/module_lib/${modulename}-removed.txt",
        sdk_version: "module_current",
    },
}
EOF
}

function make_sdk_library() {
    libnames=$1
    destdir=$2
    apexname=$3
    bp=${destdir}/Android.bp

    #test -e "$bp"
    mkdir -p "$(dirname "$bp")"

    # Remove existing java_sdk_library_import and double newlines
    existing_bp="$(sed -e '/java_sdk_library_import {/,/^}/d' "$bp" | tr -s \\n)"
    echo "$existing_bp" > "$bp"
    for libname in $libnames; do
        echo >> "$bp"
        echo "$(sdk_lib_bp ${libname} ${apexname})" | grep -v test_com.android.tethering >> "$bp"
    done
    #echo >> "$bp"

    rm -rf "${destdir}/sdk_library"
    mkdir -p "${destdir}/sdk_library/"{public,system,module_lib}
    for libname in $libnames; do
        cp public/{${libname}.jar,api/${libname}.txt,api/${libname}-removed.txt} "${destdir}/sdk_library/public"
        cp system/{${libname}.jar,api/${libname}.txt,api/${libname}-removed.txt} "${destdir}/sdk_library/system"
        cp module-lib/{${libname}.jar,api/${libname}.txt,api/${libname}-removed.txt} "${destdir}/sdk_library/module_lib"
    done
}

function copy_notices() {
    destdir=$1
    apks=$(find $destdir -name '*.apks' | head -1)
    if [[ -z "$apks" ]]; then
        echo "no apks found in $destdir" >&2
        exit
    fi
    filename=$(zipinfo -1 "$apks" *.apex */base-master.apk | head -1)
    # com.android.ipsec is not expected to have a LICENSE, so don't fail if it doesn't.
    unzip -p "$apks" "$filename" | bsdtar -xOf- assets/NOTICE.html.gz > "${destdir}/NOTICE.html.gz" || test "$2" == "com.android.ipsec"
}

function get_dest_dir() {
    if [[ "$SOURCE_TREE_TYPE" == "PARTNER" ]]; then
        echo "${DESTINATION_TREE}/vendor/partner_modules/${1}"
    elif [[ "$SOURCE_TREE_TYPE" == "GOOGLE" ]]; then
        echo -n "${DESTINATION_TREE}/vendor/unbundled_google/modules/"
        case "$1" in
            "IKEPrebuilt") echo "IpSecGooglePrebuilt";;
            "MediaFrameworkPrebuilt") echo "MediaFrameworkPrebuilt";;
            "MediaProviderPrebuilt") echo "MediaProviderGooglePrebuilt";;
            "PermissionControllerPrebuilt") echo "PermissionControllerPrebuilt";;
            "SdkExtensionsPrebuilt") echo "SdkExtensionsGooglePrebuilt";;
            "StatsdPrebuilt") echo "StatsdGooglePrebuilt";;
            "TetheringPrebuilt") echo "TetheringGooglePrebuilt";;
            "WiFiPrebuilt") echo "WifiGooglePrebuilt";;
            *) exit 1;;
        esac
    else
        # Unknown tree type
        exit 2
    fi
    #ConscryptPrebuilt ???
}

function setup_stub_prebuilts() {
    destdir=$(get_dest_dir $2)

    make_sdk_library "$1" "$destdir" "$3"
    #copy_notices "$destdir" "$3"
}

cd "$SOURCE_TREE/prebuilts/sdk/$API_LEVEL"
setup_stub_prebuilts android.net.ipsec.ike IKEPrebuilt com.android.ipsec
setup_stub_prebuilts framework-media MediaFrameworkPrebuilt com.android.media
setup_stub_prebuilts framework-mediaprovider MediaProviderPrebuilt com.android.mediaprovider
if [[ "$API_LEVEL" -ge 31 ]]; then
    setup_stub_prebuilts 'framework-permission framework-permission-s' PermissionControllerPrebuilt com.android.permission
else
    setup_stub_prebuilts framework-permission PermissionControllerPrebuilt com.android.permission
fi
setup_stub_prebuilts framework-sdkextensions SdkExtensionsPrebuilt com.android.sdkext
setup_stub_prebuilts framework-statsd StatsdPrebuilt com.android.os.statsd
setup_stub_prebuilts framework-tethering TetheringPrebuilt com.android.tethering
setup_stub_prebuilts framework-wifi WiFiPrebuilt com.android.wifi
