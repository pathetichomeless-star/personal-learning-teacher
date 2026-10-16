pragma Singleton
import QtQuick

// 学生课堂 V1 独立主题（与既有 GUI 主题解耦，避免耦合受保护模块）
QtObject {
    readonly property color bg: "#f4f6fb"
    readonly property color surface: "#ffffff"
    readonly property color surfaceAlt: "#eef2fb"
    readonly property color border: "#d9e0ef"
    readonly property color text: "#1f2a44"
    readonly property color textSecondary: "#5a6b8c"
    readonly property color textPlaceholder: "#93a1bd"
    readonly property color primary: "#2f6bff"
    readonly property color primaryHover: "#1f57e0"
    readonly property color primarySoft: "#e7efff"
    readonly property color success: "#1f9d63"
    readonly property color warn: "#d98317"
    readonly property color danger: "#d9463f"
    readonly property color avatarBg: "#dfe8ff"

    readonly property int radiusSm: 6
    readonly property int radiusMd: 10
    readonly property int radiusLg: 16
    readonly property int spacingXs: 4
    readonly property int spacingSm: 8
    readonly property int spacingMd: 12
    readonly property int spacingLg: 18
    readonly property int spacingXl: 26

    readonly property int fontXs: 12
    readonly property int fontSm: 13
    readonly property int fontMd: 15
    readonly property int fontLg: 19
    readonly property int fontXl: 26
    readonly property int fontHero: 40

    readonly property string fontFamily: "PingFang SC"
}
