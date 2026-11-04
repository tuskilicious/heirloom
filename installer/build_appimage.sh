#!/bin/sh
# heirloom_linux_x64.AppImage, from the folder build of heirloom.spec. Both tools are pinned by checksum.
set -eu
cd "$(dirname "$0")"

fetch() {
    curl -fsSL --retry 3 -o "$1" "$2"
    echo "$3  $1" | sha256sum -c -
}
tools=$(mktemp -d)
fetch "$tools/appimagetool" https://github.com/AppImage/appimagetool/releases/download/1.9.1/appimagetool-x86_64.AppImage \
    ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0
fetch "$tools/runtime" https://github.com/AppImage/type2-runtime/releases/download/20251108/runtime-x86_64 \
    2fca8b443c92510f1483a883f60061ad09b46b978b2631c807cd873a47ec260d
chmod +x "$tools/appimagetool"

rm -rf AppDir
cp -r build/heirloom AppDir
cp heirloom.desktop AppDir/
python -c "from PIL import Image; Image.open('../assets/windows_icon.ico').save('AppDir/heirloom.png')"
printf '#!/bin/sh\nexec "$(dirname "$(readlink -f "$0")")/heirloom" "$@"\n' > AppDir/AppRun
chmod +x AppDir/AppRun

mkdir -p Output
ARCH=x86_64 APPIMAGE_EXTRACT_AND_RUN=1 "$tools/appimagetool" --runtime-file "$tools/runtime" AppDir \
    Output/heirloom_linux_x64.AppImage
