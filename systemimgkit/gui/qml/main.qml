import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs
import QtQuick.Effects
import SystemImgKit 1.0

// ── SystemImgKit · instrument panel ──────────────────────────────────────
// A dark, console-style UI for debloating Android system images. Guard state
// (ok/guarded/core) is the loudest signal on screen; the log dock mirrors a
// terminal pane. Hairline rules, not framed boxes, separate sections.

ApplicationWindow {
    id: root
    visible: true
    width: 1180
    height: 740
    title: Controller.windowTitle
    color: c.bg

    // ── token system ─────────────────────────────────────────────────────
    readonly property var c: ({
        bg:      "#EDEDEF",   // work surface — soft warm grey, paper-like
        panel:   "#F6F6F7",   // rail + dock — slightly lighter raised surface
        panelHi: "#E2E2E5",   // hover / selection track
        card:    "#FBFBFC",   // function-area card — brightest raised surface
        line:    "#D0D1D5",   // hairline rules
        fg:      "#1B1D22",   // primary text — near-black, strong contrast
        fgDim:   "#565961",   // secondary — readable, not greyed-out
        fgFaint: "#8A8D95",   // tertiary — paths, low-emphasis
        accent:  "#2A6CF6",   // selection / active — deeper blue for light bg
        ok:      "#1F9D55",   // deletable
        warn:    "#C8821A",   // guarded — darker amber for legibility
        danger:  "#D43A3A",   // core / locked / brick-risk
        // function-area themes (identity colors per rail section)
        tImage:  "#2A6CF6",   // 镜像  — blue (same as accent: the entry point)
        tPipe:   "#7C5BE0",   // 流程  — violet
        tRisk:   "#C8821A",   // 风险  — amber (matches guard "guarded" semantics)
        tView:   "#1F8A8A",   // 视图  — teal
    })

    // type
    readonly property string fontUI:   Qt.application.font.family
    readonly property string fontMono: "monospace"
    readonly property int fsBase: 13
    readonly property int fsSmall: 11
    readonly property int fsMicro: 10

    // layout
    readonly property int sp: 6
    readonly property int pad: 12
    readonly property int railW: 248

    // sort state (shared; the control lives above the directory tree)
    property string sortKey: "name"
    property bool sortDesc: false
    function toggleSort(key) {
        if (root.sortKey === key) {
            root.sortDesc = !root.sortDesc
        } else {
            root.sortKey = key
            root.sortDesc = (key === "size")  // size defaults desc
        }
        Controller.appModel.sort(root.sortKey, root.sortDesc)
    }

    // guard → color
    function guardColor(g) {
        if (g === "core")    return c.danger
        if (g === "guarded") return c.warn
        return c.ok
    }
    function guardLabel(g) {
        if (g === "core")    return "核心"
        if (g === "guarded") return "受保护"
        return "可删"
    }

    // human-readable size, fixed-width-ish
    function humanSize(n) {
        var u = ["B","K","M","G","T"], i = 0
        while (n >= 1024 && i < u.length - 1) { n /= 1024; i++ }
        return i === 0 ? Math.round(n) + " B" : n.toFixed(1) + " " + u[i]
    }

    // ── icon helper ────────────────────────────────────────────────────
    // icon(name, color, size) → renders a 24×24 stroke SVG from the qrc
    // /icons prefix, recolored to `color` via MultiEffect.colorization so
    // one asset serves normal/active/disabled states. Returns an Item sized
    // to `size` (default 16). Created from the inline `iconComponent` below.
    function icon(name, color, size) {
        return iconComponent.createObject(root, {
            sourceName: name,
            tint: color || c.fg,
            iconSize: size || 16
        })
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 0
        spacing: 0

        // ── header bar ────────────────────────────────────────────────────
        // Full-width 48px header: app identity on the left (logo + wordmark,
        // moved up from the rail corner), risk + reclaim status on the right
        // (moved up from the log-dock status row).
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 48
            color: c.panel
            border.width: 0

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: root.pad
                anchors.rightMargin: root.pad
                spacing: 10

                // logo + wordmark
                Loader {
                    sourceComponent: iconComponent
                    Layout.preferredWidth: 22
                    Layout.preferredHeight: 22
                    Layout.alignment: Qt.AlignVCenter
                    onLoaded: { item.sourceName = "pack"; item.iconSize = 22; item.tint = c.accent }
                }
                Label {
                    text: "SystemImgKit"
                    color: c.fg
                    font.family: root.fontMono
                    font.pixelSize: root.fsBase
                    font.letterSpacing: 1
                    font.weight: Font.DemiBold
                    Layout.alignment: Qt.AlignVCenter
                }

                Item { Layout.fillWidth: true }

                // risk status dot + reclaim badge
                Rectangle {
                    width: 8; height: 8; radius: 4
                    color: Controller.riskOverride ? c.warn : c.ok
                    Layout.alignment: Qt.AlignVCenter
                }
                Label {
                    text: "可回收"
                    color: c.fgDim
                    font.pixelSize: root.fsMicro
                    font.letterSpacing: 1
                    Layout.alignment: Qt.AlignVCenter
                }
                Rectangle {
                    radius: 4
                    color: Qt.rgba(0.16, 0.42, 0.96, 0.14)
                    border.color: c.accent; border.width: 1
                    Layout.alignment: Qt.AlignVCenter
                    implicitWidth: reclaimLbl.implicitWidth + 14
                    implicitHeight: reclaimLbl.implicitHeight + 6
                    Label {
                        id: reclaimLbl
                        anchors.centerIn: parent
                        text: Controller.reclaimTotal
                        color: c.accent
                        font.family: root.fontMono
                        font.pixelSize: root.fsSmall
                        font.weight: Font.DemiBold
                    }
                }
            }

            // hairline under header
            Rectangle { anchors.bottom: parent.bottom; anchors.left: parent.left; anchors.right: parent.right; height: 1; color: c.line }
        }

        // ── body: rail + work surface ────────────────────────────────────
        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 0

            // ── left control rail ────────────────────────────────────────
            Rectangle {
                Layout.fillHeight: true
                Layout.preferredWidth: root.railW
                color: c.panel
                border.width: 0

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: root.pad
                    spacing: 10

                    // ── 镜像 card (theme: blue) ──────────────────────────────
                    Rectangle {
                        Layout.fillWidth: true
                        color: c.card
                        border.color: c.line; border.width: 1
                        radius: 8
                        implicitHeight: imgCardCol.implicitHeight + 20
                        Rectangle { anchors.left: parent.left; anchors.top: parent.top; anchors.bottom: parent.bottom; width: 3; color: c.tImage; radius: 2 }
                        ColumnLayout {
                            id: imgCardCol
                            anchors.fill: parent
                            anchors.leftMargin: 13; anchors.rightMargin: 10
                            anchors.topMargin: 10; anchors.bottomMargin: 10
                            spacing: 8
                            Loader {
                                sourceComponent: sectionHeaderComponent
                                Layout.fillWidth: true
                                onLoaded: { item.iconName = "open"; item.titleText = "镜像"; item.themeColor = c.tImage }
                            }

                            // structured image info — no wrapping, key/value rows
                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 3
                                visible: Controller.imageOk || Controller.imageName.length > 0

                                Label {
                                    text: Controller.imageName || "（未选择）"
                                    color: Controller.imageOk ? c.fg : c.danger
                                    font.family: root.fontMono
                                    font.pixelSize: root.fsSmall
                                    elide: Text.ElideRight
                                    Layout.fillWidth: true
                                }

                                // attribute grid: size / fmt / AVB
                                GridLayout {
                                    Layout.fillWidth: true
                                    columns: 2
                                    columnSpacing: 8
                                    rowSpacing: 2
                                    visible: Controller.imageOk

                                    Label { text: "大小"; color: c.fgDim; font.pixelSize: root.fsMicro }
                                    Label { text: Controller.imageSize; color: c.fg; font.family: root.fontMono; font.pixelSize: root.fsMicro; Layout.fillWidth: true; elide: Text.ElideRight }
                                    Label { text: "格式"; color: c.fgDim; font.pixelSize: root.fsMicro }
                                    Label { text: Controller.imageFmt; color: c.fg; font.family: root.fontMono; font.pixelSize: root.fsMicro; Layout.fillWidth: true; elide: Text.ElideRight }
                                    Label { text: "AVB页脚"; color: c.fgDim; font.pixelSize: root.fsMicro }
                                    Label { text: Controller.imageAvb; color: c.fg; font.family: root.fontMono; font.pixelSize: root.fsMicro; Layout.fillWidth: true; elide: Text.ElideRight }
                                }
                            }

                            // 打开镜像 — SecondaryButton (outline, leading icon)
                            Loader {
                                id: openBtn
                                Layout.fillWidth: true
                                sourceComponent: secondaryButtonComponent
                                onLoaded: {
                                    item.text = "打开镜像…"
                                    item.iconName = "open"
                                    item.enabled = Qt.binding(function(){ return !Controller.progressBusy })
                                }
                                Connections {
                                    target: openBtn.item
                                    function onClicked() { imageDialog.open() }
                                }
                            }

                            // ── unpack status row (auto-unpack feedback) ──────
                            // Picking an image unpacks automatically into the
                            // image's directory; this row reports that stage:
                            //   解包中… (spinning) → 已解包 (green check) → (hidden)
                            RowLayout {
                                Layout.fillWidth: true
                                Layout.topMargin: 2
                                spacing: 6
                                visible: Controller.imageOk
                                         && (Controller.currentOp === "unpack" || Controller.unpacked)
                                // status dot / spinner
                                Item {
                                    width: 14; height: 14
                                    Layout.alignment: Qt.AlignVCenter
                                    Rectangle {
                                        anchors.centerIn: parent
                                        visible: Controller.currentOp !== "unpack"
                                        width: 10; height: 10; radius: 5
                                        color: c.ok
                                    }
                                    Canvas {
                                        // check mark
                                        anchors.centerIn: parent
                                        width: 14; height: 14
                                        visible: Controller.currentOp !== "unpack"
                                        onPaint: {
                                            var ctx = getContext("2d")
                                            ctx.reset()
                                            ctx.strokeStyle = "#FFFFFF"
                                            ctx.lineWidth = 2
                                            ctx.lineCap = "round"
                                            ctx.beginPath()
                                            ctx.moveTo(2, 7)
                                            ctx.lineTo(6, 11)
                                            ctx.lineTo(12, 3)
                                            ctx.stroke()
                                        }
                                    }
                                    Rectangle {
                                        // indeterminate-ish spinner: a pulsing ring
                                        anchors.centerIn: parent
                                        visible: Controller.currentOp === "unpack"
                                        width: 12; height: 12; radius: 6
                                        color: "transparent"
                                        border.color: c.tImage; border.width: 2
                                        SequentialAnimation on opacity {
                                            running: Controller.currentOp === "unpack"
                                            loops: Animation.Infinite
                                            NumberAnimation { from: 0.3; to: 1.0; duration: 700 }
                                            NumberAnimation { from: 1.0; to: 0.3; duration: 700 }
                                        }
                                    }
                                }
                                Label {
                                    text: Controller.currentOp === "unpack" ? "解包中…"
                                          : (Controller.unpacked ? "已解包" : "")
                                    color: Controller.currentOp === "unpack" ? c.tImage : c.ok
                                    font.pixelSize: root.fsSmall
                                    font.weight: Font.Medium
                                    Layout.alignment: Qt.AlignVCenter
                                }
                                Item { Layout.fillWidth: true }
                                Label {
                                    visible: Controller.currentOp === "unpack"
                                    text: "工作区：镜像所在目录"
                                    color: c.fgFaint
                                    font.pixelSize: root.fsMicro
                                    Layout.alignment: Qt.AlignVCenter
                                }
                            }
                        }
                    }

                    // ── 流程 card (theme: violet) ──────────────────────────
                    Rectangle {
                        Layout.fillWidth: true
                        color: c.card
                        border.color: c.line; border.width: 1
                        radius: 8
                        implicitHeight: pipeCardCol.implicitHeight + 20
                        Rectangle { anchors.left: parent.left; anchors.top: parent.top; anchors.bottom: parent.bottom; width: 3; color: c.tPipe; radius: 2 }
                        ColumnLayout {
                            id: pipeCardCol
                            anchors.fill: parent
                            anchors.leftMargin: 13; anchors.rightMargin: 10
                            anchors.topMargin: 10; anchors.bottomMargin: 10
                            spacing: 8
                            Loader {
                                sourceComponent: sectionHeaderComponent
                                Layout.fillWidth: true
                                onLoaded: { item.iconName = "unpack"; item.titleText = "流程"; item.themeColor = c.tPipe }
                            }

                            // ── pipeline stepper ────────────────────────────────
                            // 2-step stepper (unpack is automatic on image pick and
                            // its status lives in the image card). Step state is
                            // DERIVED from readiness:
                            //   canPack             → [列出 done, 打包 active]
                            //   canCatalog (not pack) → [列出 active, 打包 pending]
                            //   otherwise           → [pending, pending]
                            // done = ok filled check, active = accent outline + icon,
                            // pending = dim outline, not clickable. Note: unpack
                            // success auto-triggers doCatalog, so "列出" usually
                            // resolves on its own; it stays clickable to re-list.
                            ColumnLayout {
                                id: stepper
                                Layout.fillWidth: true
                                spacing: 4

                                // global step state (0=pending,1=active,2=done) per step
                                property var states: {
                            var s = [0, 0]
                            if (Controller.canPack) { s = [2, 1] }
                            else if (Controller.canCatalog) { s = [1, 0] }
                            return s
                        }

                        Repeater {
                            model: [
                                { label: "列出应用", icon: "list", run: function(){ Controller.doCatalog() } },
                                { label: "打包",    icon: "pack", run: function(){ Controller.packDefault() } },
                            ]
                            Item {
                                Layout.fillWidth: true
                                Layout.preferredHeight: 36
                                property int st: stepper.states[index]
                                property bool clickable: st === 1 && !Controller.progressBusy

                                // active-step accent rail on the left
                                Rectangle {
                                    anchors.left: parent.left; anchors.top: parent.top; anchors.bottom: parent.bottom
                                    width: 2; radius: 1
                                    color: st === 1 ? c.accent : "transparent"
                                }
                                RowLayout {
                                    anchors.fill: parent
                                    anchors.leftMargin: 10
                                    spacing: 10
                                    // circle: done = ok check, active = accent outline + icon, pending = dim
                                    Rectangle {
                                        width: 22; height: 22; radius: 11
                                        Layout.alignment: Qt.AlignVCenter
                                        color: st === 2 ? c.ok : "transparent"
                                        border.color: st === 1 ? c.accent : (st === 2 ? c.ok : c.line)
                                        border.width: st === 1 ? 2 : 1
                                        Loader {
                                            anchors.centerIn: parent
                                            sourceComponent: iconComponent
                                            visible: st !== 2
                                            onLoaded: {
                                                item.sourceName = modelData.icon
                                                item.iconSize = 12
                                                item.tint = st === 1 ? c.accent : c.fgFaint
                                            }
                                        }
                                        // check mark for done
                                        Canvas {
                                            anchors.centerIn: parent
                                            width: 12; height: 12
                                            visible: st === 2
                                            onPaint: {
                                                var ctx = getContext("2d")
                                                ctx.reset()
                                                ctx.strokeStyle = "#FFFFFF"
                                                ctx.lineWidth = 2
                                                ctx.lineCap = "round"
                                                ctx.beginPath()
                                                ctx.moveTo(2, 6)
                                                ctx.lineTo(5, 9)
                                                ctx.lineTo(10, 3)
                                                ctx.stroke()
                                            }
                                        }
                                    }
                                    Label {
                                        text: modelData.label
                                        color: st === 0 ? c.fgFaint : (st === 1 ? c.fg : c.fg)
                                        font.pixelSize: root.fsBase
                                        font.weight: st === 1 ? Font.Medium : Font.Normal
                                        Layout.fillWidth: true
                                        Layout.alignment: Qt.AlignVCenter
                                    }
                                    Item { Layout.fillWidth: false; Layout.preferredWidth: 4 }
                                }
                                MouseArea {
                                    anchors.fill: parent
                                    cursorShape: clickable ? Qt.PointingHandCursor : Qt.ArrowCursor
                                    enabled: clickable
                                    onClicked: modelData.run()
                                }
                            }
                        }
                    }

                    // busy row — indeterminate progress bar with the cancel
                    // button embedded in its center, shown only while an
                    // operation runs. One fused element: the bar fills the
                    // row and a compact "取消" pill sits in its center.
                    //
                    // The pill follows the button style system (radius 6,
                    // fsBase label, line border) but uses the danger/risk
                    // accent on hover since cancel is a destructive action.
                    Item {
                        id: busyRow
                        Layout.fillWidth: true
                        Layout.preferredHeight: 28
                        Layout.topMargin: root.sp
                        visible: Controller.progressBusy

                        ProgressBar {
                            id: busyBar
                            anchors.fill: parent
                            indeterminate: true
                        }
                        // centered cancel pill, overlaid on the bar.
                        // At rest the pill is transparent so the progress bar
                        // reads as one uninterrupted strip; only on hover does
                        // the danger fill + border appear to signal the click.
                        Rectangle {
                            id: cancelPill
                            anchors.centerIn: busyBar
                            width: 72
                            height: 22
                            radius: 6
                            color: cancelMouse.containsMouse ? c.danger : "transparent"
                            border.color: cancelMouse.containsMouse ? c.danger : "transparent"
                            border.width: 1
                            z: 1
                            scale: cancelMouse.pressed ? 0.96 : 1.0
                            Behavior on scale { NumberAnimation { duration: 80 } }
                            RowLayout {
                                anchors.fill: parent
                                spacing: 0
                                Item { Layout.fillWidth: true }
                                Label {
                                    text: "取消"
                                    color: cancelMouse.containsMouse ? "#FFFFFF" : c.fg
                                    font.pixelSize: root.fsBase
                                    Layout.alignment: Qt.AlignVCenter
                                }
                                Item { Layout.fillWidth: true }
                            }
                            MouseArea {
                                id: cancelMouse
                                anchors.fill: parent
                                cursorShape: Qt.PointingHandCursor
                                hoverEnabled: true
                                onClicked: Controller.cancelWorker()
                            }
                        }
                    }
                        } // pipeCardCol
                    } // 流程 card

                    // ── 风险 card (theme: amber) ────────────────────────────
                    Rectangle {
                        Layout.fillWidth: true
                        color: c.card
                        border.color: c.line; border.width: 1
                        radius: 8
                        implicitHeight: riskCardCol.implicitHeight + 20
                        Rectangle { anchors.left: parent.left; anchors.top: parent.top; anchors.bottom: parent.bottom; width: 3; color: c.tRisk; radius: 2 }
                        ColumnLayout {
                            id: riskCardCol
                            anchors.fill: parent
                            anchors.leftMargin: 13; anchors.rightMargin: 10
                            anchors.topMargin: 10; anchors.bottomMargin: 10
                            spacing: 8
                            Loader {
                                sourceComponent: sectionHeaderComponent
                                Layout.fillWidth: true
                                onLoaded: { item.iconName = "risk"; item.titleText = "风险"; item.themeColor = c.tRisk }
                            }

                    CheckBox {
                        id: overrideBox
                        Layout.fillWidth: true
                        text: "允许删除受保护应用"
                        checked: Controller.riskOverride
                        onToggled: {
                            if (checked) confirmOverrideDialog.open()
                            else Controller.setOverride(false)
                        }
                        indicator: Rectangle {
                            width: 16; height: 16; radius: 4
                            y: parent.height / 2 - height / 2
                            color: overrideBox.checked ? c.accent : "transparent"
                            border.color: overrideBox.checked ? c.accent : c.line
                            border.width: 1
                            Rectangle {
                                visible: overrideBox.checked
                                anchors.centerIn: parent
                                width: 8; height: 8; radius: 2
                                color: "#FFFFFF"
                            }
                        }
                    }

                    Label { text: "目标分区大小"; color: c.fgDim; font.pixelSize: root.fsMicro; font.letterSpacing: 1; Layout.topMargin: root.sp; Layout.bottomMargin: 4 }
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 6
                        TextField {
                            id: targetSizeField
                            Layout.fillWidth: true
                            text: "0"
                            font.family: root.fontMono
                            font.pixelSize: root.fsSmall
                            color: c.fg
                            placeholderText: "0 = 原大小"
                            // Suppress the write-back while the controller pushes
                            // a probe result into the field, so the reflect
                            // (Controller → field) doesn't re-trigger parsing.
                            property bool __suppressWrite: false
                            background: Rectangle { color: c.bg; radius: 4; border.color: targetSizeField.activeFocus ? c.accent : c.line; border.width: targetSizeField.activeFocus ? 1.5 : 1 }
                            // Reflect probe/manual-originated target changes into
                            // the field — but only when the user is NOT actively
                            // editing it (no activeFocus), so typing is never
                            // clobbered by reformatting.
                            Connections {
                                target: Controller
                                function onTargetSizeGBChanged() {
                                    if (!targetSizeField.activeFocus) {
                                        targetSizeField.__suppressWrite = true
                                        targetSizeField.text = Controller.targetSizeGB
                                        targetSizeField.__suppressWrite = false
                                    }
                                }
                            }
                            onTextChanged: {
                                if (targetSizeField.__suppressWrite)
                                    return
                                var gb = parseFloat(text.trim()) || 0
                                // GB -> blocks (1 GB = 1e9 bytes); use the image's
                                // real block size (manifest, 4096 fallback) so
                                // manual entry and the probe agree on units.
                                var bs = Controller.imageBlockSize || 4096
                                Controller.targetBlocks = gb > 0 ? Math.round(gb * 1e9 / bs) : 0
                            }
                        }
                        Label { text: "GB"; color: c.fgDim; font.pixelSize: root.fsMicro }
                    }
                    Label {
                        Layout.fillWidth: true
                        text: "设为设备 system 分区大小(如 7.68),0=按原镜像。填小于原值的可缩小镜像以刷进更小分区。"
                        color: c.fgFaint
                        font.pixelSize: root.fsMicro
                        wrapMode: Text.WordWrap
                        Layout.bottomMargin: 2
                    }
                    // 探测设备分区 — SecondaryButton (outline, leading icon)
                    Loader {
                        id: probeBtn
                        Layout.fillWidth: true
                        sourceComponent: secondaryButtonComponent
                        onLoaded: {
                            item.iconName = "probe"
                            item.text = Qt.binding(function(){ return Controller.progressBusy ? "探测中…" : "探测设备分区" })
                            item.enabled = Qt.binding(function(){ return !Controller.progressBusy })
                        }
                        Connections {
                            target: probeBtn.item
                            function onClicked() { Controller.probeDevicePartition() }
                        }
                    }
                        } // riskCardCol
                    } // 风险 card

                    // ── 视图 card (theme: teal) ─────────────────────────────
                    Rectangle {
                        Layout.fillWidth: true
                        color: c.card
                        border.color: c.line; border.width: 1
                        radius: 8
                        implicitHeight: viewCardCol.implicitHeight + 20
                        Rectangle { anchors.left: parent.left; anchors.top: parent.top; anchors.bottom: parent.bottom; width: 3; color: c.tView; radius: 2 }
                        ColumnLayout {
                            id: viewCardCol
                            anchors.fill: parent
                            anchors.leftMargin: 13; anchors.rightMargin: 10
                            anchors.topMargin: 10; anchors.bottomMargin: 10
                            spacing: 8
                            Loader {
                                sourceComponent: sectionHeaderComponent
                                Layout.fillWidth: true
                                onLoaded: { item.iconName = "files"; item.titleText = "视图"; item.themeColor = c.tView }
                            }
                    TabBar {
                        id: tabs
                        Layout.fillWidth: true
                        background: Rectangle { color: "transparent" }
                        TabButton {
                            text: "应用"
                            width: implicitWidth
                            background: Rectangle {
                                color: tabs.currentIndex === 0 ? c.panelHi : "transparent"; radius: 4
                                Rectangle { anchors.bottom: parent.bottom; anchors.left: parent.left; anchors.right: parent.right; height: 2; color: tabs.currentIndex === 0 ? c.accent : "transparent"; radius: 1 }
                            }
                            contentItem: Label { text: parent.text; color: tabs.currentIndex === 0 ? c.fg : c.fgDim; font.pixelSize: root.fsSmall; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                        }
                        TabButton {
                            text: "大文件"
                            width: implicitWidth
                            background: Rectangle {
                                color: tabs.currentIndex === 1 ? c.panelHi : "transparent"; radius: 4
                                Rectangle { anchors.bottom: parent.bottom; anchors.left: parent.left; anchors.right: parent.right; height: 2; color: tabs.currentIndex === 1 ? c.accent : "transparent"; radius: 1 }
                            }
                            contentItem: Label { text: parent.text; color: tabs.currentIndex === 1 ? c.fg : c.fgDim; font.pixelSize: root.fsSmall; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                        }
                    }
                        } // viewCardCol
                    } // 视图 card

                    Item { Layout.fillHeight: true } // top-align
                }
            }

            // ── right work surface ────────────────────────────────────────
            Rectangle {
                Layout.fillWidth: true
                Layout.fillHeight: true
                color: c.bg

                StackLayout {
                    id: stack
                    anchors.fill: parent
                    currentIndex: tabs.currentIndex

                    // apps: left directory tree + right app list
                    RowLayout {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        spacing: 0

                        // left: sort control + directory tree
                        ColumnLayout {
                            Layout.fillHeight: true
                            Layout.fillWidth: false
                            Layout.preferredWidth: 200
                            Layout.maximumWidth: 200
                            spacing: 4

                            // sort control — compact, lives here (no column header row)
                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 6
                                Label { text: "排序"; color: c.fgDim; font.pixelSize: root.fsMicro; font.letterSpacing: 1 }
                                ComboBox {
                                    Layout.fillWidth: true
                                    model: ["名称", "大小", "保护级别", "文件数"]
                                    currentIndex: 0
                                    onActivated: {
                                        var keys = ["name", "size", "guard", "fileCount"]
                                        root.sortKey = keys[index]
                                        root.sortDesc = (root.sortKey === "size")
                                        Controller.appModel.sort(root.sortKey, root.sortDesc)
                                    }
                                    palette.text: root.c.fg
                                    palette.window: root.c.panel
                                    palette.highlightedText: "#FFFFFF"
                                }
                                Button {
                                    text: root.sortDesc ? "降序" : "升序"
                                    flat: true
                                    Layout.preferredWidth: 56
                                    onClicked: {
                                        root.sortDesc = !root.sortDesc
                                        Controller.appModel.sort(root.sortKey, root.sortDesc)
                                    }
                                    contentItem: RowLayout {
                                        spacing: 4
                                        Loader {
                                            sourceComponent: iconComponent
                                            Layout.alignment: Qt.AlignVCenter
                                            onLoaded: { item.sourceName = "sort"; item.iconSize = 13; item.tint = c.fgDim }
                                        }
                                        Label {
                                            text: root.sortDesc ? "降序" : "升序"
                                            color: c.fgDim
                                            font.pixelSize: root.fsMicro
                                            Layout.alignment: Qt.AlignVCenter
                                        }
                                    }
                                }
                            }

                        // left: directory tree
                        ListView {
                            id: dirTree
                            Layout.fillHeight: true
                            Layout.fillWidth: true
                            clip: true
                            model: Controller.sections
                            spacing: 1
                            currentIndex: 0
                            highlight: Rectangle { color: c.panelHi; radius: 3 }
                            delegate: Item {
                                width: dirTree.width
                                height: 46
                                MouseArea {
                                    anchors.fill: parent
                                    onClicked: {
                                        dirTree.currentIndex = index
                                        Controller.appModel.setFilterSection(modelData.key)
                                    }
                                }
                                RowLayout {
                                    anchors.fill: parent
                                    anchors.leftMargin: 12
                                    anchors.rightMargin: 10
                                    spacing: 8
                                    Rectangle {
                                        width: 3; height: 30; radius: 1
                                        color: dirTree.currentIndex === index ? c.accent : c.line
                                        Layout.alignment: Qt.AlignVCenter
                                    }
                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        spacing: 1
                                        RowLayout {
                                            Layout.fillWidth: true
                                            spacing: 6
                                            Label {
                                                text: modelData.label
                                                color: dirTree.currentIndex === index ? c.fg : c.fgDim
                                                font.pixelSize: root.fsSmall
                                                font.weight: dirTree.currentIndex === index ? Font.DemiBold : Font.Normal
                                                Layout.fillWidth: true
                                                elide: Text.ElideRight
                                            }
                                            Label {
                                                text: String(modelData.count)
                                                color: c.fgFaint
                                                font.family: root.fontMono
                                                font.pixelSize: root.fsMicro
                                                Layout.alignment: Qt.AlignVCenter
                                            }
                                        }
                                        // raw path, e.g. system/priv-app
                                        Label {
                                            text: modelData.key
                                            color: c.fgFaint
                                            font.family: root.fontMono
                                            font.pixelSize: root.fsMicro
                                            elide: Text.ElideRight
                                            Layout.fillWidth: true
                                        }
                                    }
                                }
                            }
                            Loader {
                                anchors.centerIn: parent
                                visible: dirTree.count === 0
                                sourceComponent: emptyStateComponent
                                onLoaded: {
                                    item.iconName = "unpack"
                                    item.titleText = "运行流程以列出目录"
                                    item.subtitleText = "先解包镜像"
                                }
                            }
                            onModelChanged: {
                                if (count > 0) {
                                    currentIndex = 0
                                    Controller.appModel.setFilterSection(Controller.sections[0].key)
                                }
                            }
                        }
                        } // ColumnLayout (sort control + dirTree)

                        Rectangle { Layout.fillHeight: true; width: 1; color: c.line }

                        // right: app list
                        ColumnLayout {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            spacing: 0

                        ListView {
                            id: appList
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            clip: true
                            model: Controller.appModel
                            spacing: 1
                            delegate: appCard

                            Loader {
                                anchors.centerIn: parent
                                visible: appList.count === 0
                                sourceComponent: emptyStateComponent
                                onLoaded: {
                                    item.iconName = "list"
                                    item.titleText = "该目录无应用"
                                    item.subtitleText = "选择左侧其他分区，或运行「列出应用」"
                                }
                            }
                        }
                        } // ColumnLayout (right app list)
                    } // RowLayout (apps tab)

                    // big files list
                    ListView {
                        id: bigFileList
                        clip: true
                        model: Controller.bigFileModel
                        spacing: 1
                        delegate: bigFileRow
                        Loader {
                            anchors.centerIn: parent
                            visible: bigFileList.count === 0
                            sourceComponent: emptyStateComponent
                            onLoaded: {
                                item.iconName = "bigfile"
                                item.titleText = "未加载大文件"
                                item.subtitleText = "运行「列出应用」后将显示占用最大的文件"
                            }
                        }
                    }
                }
            }
        }

        // ── status / log dock (full width) ────────────────────────────────
        ColumnLayout {
            Layout.fillWidth: true
            spacing: 0

            // drag handle to resize the dock
            Rectangle {
                Layout.fillWidth: true
                height: 6
                color: "transparent"
                Rectangle { anchors.centerIn: parent; width: 40; height: 2; radius: 1; color: c.line }
                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.SplitVCursor
                    property real startY: 0
                    property real startH: 0
                    onPressed: { startY = mouseY; startH = dockBody.height }
                    onPositionChanged: {
                        var nh = startH + (mouseY - startY)
                        dockBody.height = Math.max(80, Math.min(400, nh))
                    }
                }
            }

            Rectangle {
                id: dockBody
                Layout.fillWidth: true
                height: 168
                color: c.panel
                border.width: 0

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: root.pad
                    spacing: 6

                    // status row — "日志" title with a terminal glyph (left).
                    // risk dot + reclaim moved up to the header in P3.
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 6

                        Loader {
                            sourceComponent: iconComponent
                            Layout.alignment: Qt.AlignVCenter
                            onLoaded: { item.sourceName = "list"; item.iconSize = 13; item.tint = c.fgDim }
                        }
                        Label {
                            text: "日志"
                            color: c.fgDim
                            font.pixelSize: root.fsMicro
                            font.letterSpacing: 1
                            Layout.alignment: Qt.AlignVCenter
                        }
                        Item { Layout.fillWidth: true }
                    }

                    Rectangle { Layout.fillWidth: true; height: 1; color: c.line }

                    // log stream — no wrap (long rsync lines scroll horizontally),
                    // auto-scrolls to the bottom as new lines arrive.
                    Flickable {
                        id: logFlick
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        contentWidth: logContent.width
                        contentHeight: logContent.height
                        flickableDirection: Flickable.VerticalFlick
                        boundsBehavior: Flickable.StopAtBounds

                        Text {
                            id: logContent
                            // live tail: render the most recent line in primary
                            // fg, older lines dimmed (fgFaint). Built as rich text
                            // so per-line color is possible; HTML-escape each line.
                            textFormat: Text.RichText
                            text: {
                                var lines = Controller.warnings
                                var n = lines.length
                                var out = []
                                for (var i = 0; i < n; i++) {
                                    var s = String(lines[i])
                                        .replace(/&/g, "&amp;")
                                        .replace(/</g, "&lt;")
                                        .replace(/>/g, "&gt;")
                                    var col = (i === n - 1) ? c.fg : c.fgFaint
                                    out.push("<span style=\"color:" + col + "\">" + s + "</span>")
                                }
                                return out.join("<br>")
                            }
                            color: c.fg
                            font.family: root.fontMono
                            font.pixelSize: root.fsSmall
                            // No wrap: let long lines extend; horizontal scroll via contentWidth
                            width: Math.max(logFlick.width, implicitWidth)
                            onTextChanged: {
                                if (logFlick.contentHeight > logFlick.height)
                                    logFlick.contentY = logFlick.contentHeight - logFlick.height
                            }
                        }
                        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                        ScrollBar.horizontal: ScrollBar { policy: ScrollBar.AsNeeded }
                    }
                }
            }
        }
    }

    // ── app row delegate ─────────────────────────────────────────────────
    Component {
        id: appCard
        Item {
            width: appList.width
            height: 44

            // selection track
            Rectangle {
                anchors.fill: parent
                anchors.leftMargin: 0
                color: model.checked ? Qt.rgba(0.16, 0.42, 0.96, 0.16)
                     : (hover.hovered ? c.panelHi : "transparent")
            }
            // guard edge — a 3px left bar encoding safety state
            Rectangle {
                width: 3; height: parent.height
                color: guardColor(model.guard)
                opacity: model.guard === "none" ? 0.45 : 1.0
            }
            HoverHandler { id: hover }

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 14
                anchors.rightMargin: 12
                spacing: 10

                CheckBox {
                    id: appCheck
                    checked: model.checked
                    enabled: model.guard !== "core"
                             && !(model.guard === "guarded" && !Controller.riskOverride)
                    onToggled: Controller.appModel.setChecked(model.index, checked)
                    Layout.preferredWidth: 24
                    Layout.maximumWidth: 24
                    indicator: Rectangle {
                        width: 16; height: 16; radius: 4
                        y: appCheck.height / 2 - height / 2
                        color: appCheck.checked ? c.accent : "transparent"
                        border.color: appCheck.checked ? c.accent : c.line
                        border.width: 1
                        Rectangle {
                            visible: appCheck.checked
                            anchors.centerIn: parent
                            width: 8; height: 8; radius: 2
                            color: "#FFFFFF"
                        }
                    }
                }

                Label {
                    text: model.name
                    color: model.guard === "core" ? c.danger : c.fg
                    font.pixelSize: root.fsBase
                    font.weight: Font.Medium
                    elide: Text.ElideRight
                    Layout.fillWidth: true
                }

                // guard column — always 56 wide so it aligns with the header;
                // the badge inside is shown only when guarded/core.
                Item {
                    Layout.preferredWidth: 56
                    Layout.fillHeight: true
                    Rectangle {
                        visible: model.guard !== "none"
                        anchors.centerIn: parent
                        radius: 4
                        implicitWidth: guardTag.implicitWidth + 12
                        implicitHeight: guardTag.implicitHeight + 6
                        color: Qt.rgba(guardColor(model.guard).r, guardColor(model.guard).g, guardColor(model.guard).b, 0.18)
                        border.color: guardColor(model.guard); border.width: 1
                        Label {
                            id: guardTag
                            anchors.centerIn: parent
                            text: guardLabel(model.guard)
                            color: guardColor(model.guard)
                            font.family: root.fontMono
                            font.pixelSize: root.fsMicro
                        }
                    }
                }

                Label {
                    text: humanSize(model.size)
                    color: c.fg
                    font.family: root.fontMono
                    font.pixelSize: root.fsSmall
                    Layout.alignment: Qt.AlignRight | Qt.AlignVCenter
                    Layout.preferredWidth: 84
                }
                Label {
                    text: String(model.fileCount) + " 文件"
                    color: c.fgDim
                    font.family: root.fontMono
                    font.pixelSize: root.fsMicro
                    Layout.alignment: Qt.AlignRight | Qt.AlignVCenter
                    Layout.preferredWidth: 56
                }
            }

            // hairline between rows
            Rectangle { anchors.bottom: parent.bottom; anchors.left: parent.left; anchors.right: parent.right; height: 1; color: c.line; opacity: 0.5 }

            ToolTip {
                visible: hover.hovered && (model.guardReason ?? "").length > 0
                text: model.guardReason ?? ""
                delay: 250
                background: Rectangle { color: c.bg; border.color: c.line; border.width: 1; radius: 4 }
                contentItem: Label {
                    text: parent.text
                    color: c.fg
                    font.pixelSize: root.fsSmall
                }
            }
        }
    }

    // ── big-file row delegate ───────────────────────────────────────────
    Component {
        id: bigFileRow
        Item {
            width: bigFileList.width
            height: 40

            Rectangle {
                anchors.fill: parent
                color: model.checked ? Qt.rgba(0.16, 0.42, 0.96, 0.16)
                     : (hover.hovered ? c.panelHi : "transparent")
            }
            // guard edge — 3px left bar encoding safety state (same semantics
            // as the app cards: core=danger, guarded=warn, none=ok/faint).
            Rectangle {
                width: 3; height: parent.height
                color: guardColor(model.guard)
                opacity: model.guard === "none" ? 0.45 : 1.0
            }
            HoverHandler { id: hover }

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 14
                anchors.rightMargin: 12
                spacing: 10

                CheckBox {
                    id: bigCheck
                    checked: model.checked
                    // core never; guarded only with override (same rule as the
                    // app list — the big-file view cannot bypass the toggle).
                    enabled: model.guard !== "core"
                             && !(model.guard === "guarded" && !Controller.riskOverride)
                    onToggled: Controller.bigFileModel.setChecked(model.index, checked)
                    Layout.maximumWidth: 24
                    indicator: Rectangle {
                        width: 16; height: 16; radius: 4
                        y: bigCheck.height / 2 - height / 2
                        color: bigCheck.checked ? c.accent : "transparent"
                        border.color: bigCheck.checked ? c.accent : c.line
                        border.width: 1
                        Rectangle { visible: bigCheck.checked; anchors.centerIn: parent; width: 8; height: 8; radius: 2; color: "#FFFFFF" }
                    }
                }

                Label {
                    text: model.path
                    color: model.guard === "core" ? c.danger : c.fg
                    font.family: root.fontMono
                    font.pixelSize: root.fsSmall
                    elide: Text.ElideRight
                    Layout.fillWidth: true
                }

                Label {
                    text: humanSize(model.size)
                    color: c.fg
                    font.family: root.fontMono
                    font.pixelSize: root.fsSmall
                    Layout.alignment: Qt.AlignRight | Qt.AlignVCenter
                    Layout.preferredWidth: 90
                }
                // guard badge — shown only for guarded/core
                Item {
                    Layout.preferredWidth: 56
                    Layout.fillHeight: true
                    Rectangle {
                        visible: model.guard !== "none"
                        anchors.centerIn: parent
                        radius: 4
                        implicitWidth: bigGuardTag.implicitWidth + 12
                        implicitHeight: bigGuardTag.implicitHeight + 6
                        color: Qt.rgba(guardColor(model.guard).r, guardColor(model.guard).g, guardColor(model.guard).b, 0.18)
                        border.color: guardColor(model.guard); border.width: 1
                        Label {
                            id: bigGuardTag
                            anchors.centerIn: parent
                            text: guardLabel(model.guard)
                            color: guardColor(model.guard)
                            font.family: root.fontMono
                            font.pixelSize: root.fsMicro
                        }
                    }
                }
            }
            Rectangle { anchors.bottom: parent.bottom; anchors.left: parent.left; anchors.right: parent.right; height: 1; color: c.line; opacity: 0.4 }
        }
    }

    // ── dialogs (native) ──────────────────────────────────────────────────
    // GUI runs as a normal user now, so the native GTK file dialog can reach
    // the user's home and any directory. Root is only acquired per-operation
    // via the root helper (see gui/rootops.py), not for the whole process.
    FileDialog {
        id: imageDialog
        title: "打开 system.img"
        nameFilters: ["镜像文件 (*.img)"]
        // Picking an image starts unpacking immediately into the image's own
        // directory (no separate "解包" step, no workspace folder dialog).
        onAccepted: Controller.openImageAndUnpack(currentFile)
    }


    MessageDialog {
        id: confirmOverrideDialog
        title: "风险覆盖"
        text: "开启后将允许删除“受保护”应用（例如 Play 商店、助手、OTA 等）。\n核心应用仍锁定。删除操作会被记录。\n\n确定要继续吗？"
        buttons: MessageDialog.Yes | MessageDialog.No
        onButtonClicked: {
            if (button === MessageDialog.Yes) Controller.setOverride(true)
            else overrideBox.checked = false
        }
    }
    MessageDialog {
        id: infoDialog; title: ""; text: ""; buttons: MessageDialog.Ok
        Connections { target: Controller; function onInfoMessage(t, m) { infoDialog.title = t; infoDialog.text = m; infoDialog.open() } }
    }
    MessageDialog {
        id: errorDialog; title: ""; text: ""; buttons: MessageDialog.Ok
        Connections { target: Controller; function onErrorMessage(t, m) { errorDialog.title = t; errorDialog.text = m; errorDialog.open() } }
    }
    MessageDialog {
        id: guardDialog; title: "已锁定"; text: ""; buttons: MessageDialog.Ok
        Connections { target: Controller; function onGuardBlocked(name, reason) { guardDialog.text = reason; guardDialog.open() } }
    }

    // ── icon component ──────────────────────────────────────────────────
    // Inline reusable glyph: an Image loading the SVG from qrc, recolored
    // to `tint` via MultiEffect.colorization (Qt 6.5+; ColorOverlay is gone
    // in Qt6 without Qt5Compat). Properties:
    //   sourceName — icon file stem under qrc:/icons (e.g. "open")
    //   tint       — recolor target (a token color)
    //   iconSize   — rendered px
    Component {
        id: iconComponent
        Item {
            property string sourceName: ""
            property color tint: c.fg
            property int iconSize: 16
            width: iconSize
            height: iconSize
            Image {
                id: iconImg
                anchors.fill: parent
                source: sourceName.length ? "qrc:/icons/" + sourceName + ".svg" : ""
                fillMode: Image.Pad
                sourceSize.width: 24
                sourceSize.height: 24
                visible: false
            }
            MultiEffect {
                anchors.fill: iconImg
                source: iconImg
                colorization: 1.0
                colorizationColor: parent.tint
            }
        }
    }

    // ── empty-state component (P4) ─────────────────────────────────────
    // Centered icon + title + subtitle for the three ListView empty states.
    // Properties: iconName, titleText, subtitleText. Place a Loader with
    // this sourceComponent inside the ListView, anchored centerIn: parent,
    // visible when the list count === 0; set the three props in onLoaded.
    Component {
        id: emptyStateComponent
        ColumnLayout {
            id: es
            property string iconName: ""
            property string titleText: ""
            property string subtitleText: ""
            spacing: 8
            Loader {
                sourceComponent: iconComponent
                Layout.alignment: Qt.AlignHCenter
                onLoaded: { item.sourceName = es.iconName; item.iconSize = 32; item.tint = c.fgFaint }
            }
            Label {
                text: es.titleText
                color: c.fgDim
                font.pixelSize: root.fsBase
                Layout.alignment: Qt.AlignHCenter
            }
            Label {
                text: es.subtitleText
                color: c.fgFaint
                font.pixelSize: root.fsMicro
                Layout.alignment: Qt.AlignHCenter
            }
        }
    }

    // ── section header component (function-area theming) ───────────────
    // A card's title row: a theme-colored rounded square with an icon, plus
    // the section title. Properties: iconName, titleText, themeColor.
    // Used inside each rail section card (see sectionCardComponent).
    Component {
        id: sectionHeaderComponent
        RowLayout {
            id: sh
            property string iconName: ""
            property string titleText: ""
            property color themeColor: c.accent
            spacing: 8
            Rectangle {
                width: 20; height: 20; radius: 5
                color: Qt.rgba(sh.themeColor.r, sh.themeColor.g, sh.themeColor.b, 0.16)
                border.color: sh.themeColor; border.width: 1
                Layout.alignment: Qt.AlignVCenter
                Loader {
                    anchors.centerIn: parent
                    sourceComponent: iconComponent
                    onLoaded: { item.sourceName = sh.iconName; item.iconSize = 12; item.tint = sh.themeColor }
                }
            }
            Label {
                text: sh.titleText
                color: c.fg
                font.pixelSize: root.fsBase
                font.weight: Font.DemiBold
                Layout.fillWidth: true
                Layout.alignment: Qt.AlignVCenter
            }
        }
    }

    // ── button style components (P1) ────────────────────────────────────
    // Three reusable button looks sharing a 32px min height, radius 6, and a
    // leading icon + label content row. Each emits `clicked`; the caller
    // binds `text`, `iconName`, `enabled` via the Loader's item and connects
    // to `clicked` through a Connections block targeting the Loader's item.
    //
    //   PrimaryButton   — accent fill, white text   (the action of consequence)
    //   SecondaryButton — outline, fg text          (open / probe)
    //   GhostButton     — borderless, dim text      (cancel)
    Component {
        id: primaryButtonComponent
        Item {
            id: pb
            signal clicked()
            property string text: ""
            property string iconName: ""
            property bool enabled: true
            implicitHeight: 32
            Layout.fillWidth: true
            Layout.preferredHeight: 32
            scale: (ma.pressed && pb.enabled) ? 0.98 : 1.0
            Behavior on scale { NumberAnimation { duration: 80 } }
            Rectangle {
                anchors.fill: parent
                radius: 6
                color: pb.enabled ? (ma.containsMouse ? Qt.darker(c.accent, 108) : c.accent) : c.line
            }
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 12
                anchors.rightMargin: 12
                spacing: 8
                Loader {
                    sourceComponent: iconComponent
                    Layout.alignment: Qt.AlignVCenter
                    visible: pb.iconName.length
                    onLoaded: { item.sourceName = pb.iconName; item.iconSize = 16; item.tint = "#FFFFFF" }
                }
                Label {
                    text: pb.text
                    color: "#FFFFFF"
                    font.pixelSize: root.fsBase
                    font.weight: Font.Medium
                    Layout.fillWidth: true
                    horizontalAlignment: Text.AlignLeft
                    verticalAlignment: Text.AlignVCenter
                }
            }
            MouseArea {
                id: ma
                anchors.fill: parent
                cursorShape: pb.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                enabled: pb.enabled
                hoverEnabled: true
                onClicked: pb.clicked()
            }
        }
    }

    Component {
        id: secondaryButtonComponent
        Item {
            id: sb
            signal clicked()
            property string text: ""
            property string iconName: ""
            property bool enabled: true
            implicitHeight: 32
            Layout.fillWidth: true
            Layout.preferredHeight: 32
            Rectangle {
                anchors.fill: parent
                radius: 6
                color: ma.containsMouse && sb.enabled ? c.panelHi : "transparent"
                border.color: sb.enabled ? c.line : c.line
                border.width: 1
            }
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 12
                anchors.rightMargin: 12
                spacing: 8
                Loader {
                    sourceComponent: iconComponent
                    Layout.alignment: Qt.AlignVCenter
                    visible: sb.iconName.length
                    onLoaded: { item.sourceName = sb.iconName; item.iconSize = 16; item.tint = sb.enabled ? c.fg : c.fgFaint }
                }
                Label {
                    text: sb.text
                    color: sb.enabled ? c.fg : c.fgFaint
                    font.pixelSize: root.fsBase
                    Layout.fillWidth: true
                    horizontalAlignment: Text.AlignLeft
                    verticalAlignment: Text.AlignVCenter
                }
            }
            MouseArea {
                id: ma
                anchors.fill: parent
                cursorShape: sb.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                enabled: sb.enabled
                hoverEnabled: true
                onClicked: sb.clicked()
            }
        }
    }

    Component {
        id: ghostButtonComponent
        Item {
            id: gb
            signal clicked()
            property string text: ""
            property string iconName: ""
            property bool enabled: true
            implicitHeight: 32
            Layout.fillWidth: true
            Layout.preferredHeight: 32
            Rectangle {
                anchors.fill: parent
                radius: 6
                color: ma.containsMouse && gb.enabled ? c.panelHi : "transparent"
            }
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 12
                anchors.rightMargin: 12
                spacing: 8
                Loader {
                    sourceComponent: iconComponent
                    Layout.alignment: Qt.AlignVCenter
                    visible: gb.iconName.length
                    onLoaded: { item.sourceName = gb.iconName; item.iconSize = 16; item.tint = gb.enabled ? c.fgDim : c.fgFaint }
                }
                Label {
                    text: gb.text
                    color: gb.enabled ? (ma.containsMouse ? c.fg : c.fgDim) : c.fgFaint
                    font.pixelSize: root.fsBase
                    Layout.fillWidth: true
                    horizontalAlignment: Text.AlignLeft
                    verticalAlignment: Text.AlignVCenter
                }
            }
            MouseArea {
                id: ma
                anchors.fill: parent
                cursorShape: gb.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                enabled: gb.enabled
                hoverEnabled: true
                onClicked: gb.clicked()
            }
        }
    }
}
