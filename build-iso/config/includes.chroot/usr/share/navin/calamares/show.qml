/* NAVIN OS 1.2 installer slideshow (Calamares slideshowAPI 2). Text only, light NAVIN colours. */
import QtQuick 2.0;
import calamares.slideshow 1.0;

Presentation
{
    id: presentation

    function onActivate() { }
    function onLeave() { }

    Timer {
        interval: 9000
        running: presentation.activatedInCalamares
        repeat: true
        onTriggered: presentation.goToNextSlide()
    }

    component NavinSlide: Slide {
        property string heading: ""
        property string body: ""
        Rectangle { anchors.fill: parent; color: "#f4f7fb" }
        Column {
            anchors.centerIn: parent
            width: Math.min(parent.width - 60, 620)
            spacing: 18
            Text { text: heading; color: "#14202b"; font.pixelSize: 26; font.bold: true; wrapMode: Text.WordWrap; width: parent.width; horizontalAlignment: Text.AlignHCenter }
            Text { text: body; color: "#33475b"; font.pixelSize: 16; wrapMode: Text.WordWrap; width: parent.width; horizontalAlignment: Text.AlignHCenter; textFormat: Text.StyledText }
        }
    }

    NavinSlide {
        heading: qsTr("Installing NAVIN OS 1.2")
        body: qsTr("Debian 13 base. The rest is automatic and takes about 10–20 minutes.<br/>Keep the charger connected and do not remove the USB drive.")
    }
    NavinSlide {
        heading: qsTr("Dual boot with Windows")
        body: qsTr("If you chose <b>Install alongside</b>, Windows stays untouched.<br/>Every start shows the NAVIN boot menu: pick NAVIN OS or Windows.")
    }
    NavinSlide {
        heading: qsTr("Works offline")
        body: qsTr("The UEFI boot loader is copied from the USB, so no internet is needed to finish.<br/>Updates arrive later from the Update Manager.")
    }
    NavinSlide {
        heading: qsTr("Your first start")
        body: qsTr("System Center (Super+I) checks drivers, fans and temperatures.<br/>App Store installs Debian and Flathub apps. Windows .exe files open with NAVIN EXE Runner.")
    }
    NavinSlide {
        heading: qsTr("Touchpad gestures")
        body: qsTr("Three fingers: switch workspaces, show windows or the desktop.<br/>Two fingers: pinch to zoom. Alt+Tab shows a picture of every window.")
    }
}
