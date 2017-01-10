import {Component, ViewChild} from '@angular/core';
import {NavController, NavParams, List, ToastController} from 'ionic-angular';
import {iChargerService} from "../../services/icharger.service";
import {PresetPage} from "../preset/preset";
import {Preset, ChemistryType} from "../preset/preset-class";

@Component({
    selector: 'page-preset-list',
    templateUrl: 'preset-list.html'
})
export class PresetListPage {
    public presets: Array<Preset>;
    @ViewChild(List) list: List;

    constructor(public navCtrl: NavController,
                public chargerService: iChargerService,
                public toastController: ToastController,
                public navParams: NavParams) {
    }

    ionViewDidLoad() {
        this.chargerService.getPresets().subscribe(presetsList => {
            this.presets = presetsList;

            // Was used during testing, to move to a known preset and edit it.
            // if (this.presets.length) {
            //     this.navCtrl.push(PresetPage, this.presets[1]);
            // }
        });
    }

    editPreset(preset) {
        if (preset.type == ChemistryType.LiPo) {
            this.navCtrl.push(PresetPage, preset);
        } else {
            let toast = this.toastController.create({
                message: "Only support editing Lipo for now",
                duration: 2000,
                // dismissOnPageChange: true, // causes an exception. meh.
                position: "top"
            });

            toast.present();
        }
    }

    chemistyClass(preset) {
        return "chemistry-" + preset['type_str'];
    }

    tagsForPreset(preset) {
        let tags = [];
        if (preset.type_str) {
            tags.push(preset.type_str);
        } else {
            tags.push("Unknown");
        }
        if (preset['charge_current']) {
            tags.push("+ " + preset['charge_current'] + 'A');
        }
        if (preset['discharge_current']) {
            tags.push("- " + preset['discharge_current'] + 'A');
        }
        return tags;
    }
}