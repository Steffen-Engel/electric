import {Injectable} from "@angular/core";
import {Http, Headers, RequestOptions} from "@angular/http";
import {Observable} from "rxjs";
import {Configuration} from "./configuration.service";
import {Events} from "ionic-angular";
import {Preset} from "../pages/preset/preset-class";
import {Channel} from "../models/channel";

const CHARGER_CONNECTED_EVENT: string = 'charger.connected'; // connected!
const CHARGER_DISCONNECTED_EVENT: string = 'charger.disconnected'; // connection error
const CHARGER_STATUS_ERROR: string = 'charger.status.error'; // when we can't get the charger status
const CHARGER_COMMAND_FAILURE: string = 'charger.command.error'; // when a save command goes bad
const CHARGER_CHANNEL_EVENT: string = 'charger.activity';

export enum ChargerType {
    iCharger4010Duo = 64,
    iCharger308Duo = 66
}

export let ChargerMetadata = {};
ChargerMetadata[ChargerType.iCharger308Duo] = {'maxAmps': 30, 'name': 'iCharger 308', 'tag': 'DUO'};
ChargerMetadata[ChargerType.iCharger4010Duo] = {'maxAmps': 40, 'name': 'iCharger 4010', 'tag': 'DUO'};

@Injectable()
export class iChargerService {
    chargerStatus: {} = {};
    channelSnapshots: any[] = [];
    numberOfChannels: number = 0;

    private channelStateObservable;

    public constructor(public http: Http,
                       public events: Events,
                       public config: Configuration) {
        this.channelStateObservable = [];
    }

    isConnectedToServer(): boolean {
        return Object.keys(this.chargerStatus).length > 0;
    }

    isConnectedToCharger(): boolean {
        if (!this.isConnectedToServer()) {
            return false;
        }

        if (this.channelSnapshots) {
            let statusString = this.chargerStatus['charger_presence'];
            let channelCount = Number(this.chargerStatus['channel_count']);
            return statusString === 'connected' && channelCount > 0;
        }
        return false;
    }

    anyNetworkOrConnectivityProblems() {
        let haveNetwork = this.isNetworkAvailable();
        let haveCharger = this.isConnectedToCharger();
        let haveServer = this.isConnectedToServer();
        return !haveNetwork || !haveCharger || !haveServer;
    }

    isNetworkAvailable(): boolean {
        return true;
    }

    getNumberOfChannels(): number {
        if (!this.isConnectedToServer()) {
            return 0;
        }
        return this.numberOfChannels;
    }


    getPresets(): Observable<any> {
        let url = this.getChargerURL("/preset");
        return this.http.get(url).map(v => {
            // This should be a list of presets
            let presetList = [];
            let arrayOfPresets = v.json();
            for (let presetDict of arrayOfPresets) {
                presetList.push(new Preset(presetDict));
            }
            return presetList;
        });
    }

    getChargerStatus(): Observable<any> {
        return Observable.timer(1000, 1000)
            .flatMap((v) => {
                return this.http.get(this.getChargerURL("/status"));
            })
            .map((v) => {
                let connected = this.isConnectedToCharger();
                this.chargerStatus = v.json();

                let chargerHasAppeared = !connected && this.isConnectedToCharger();
                if (chargerHasAppeared) {
                    this.chargerDidAppear(this.chargerStatus);
                }
                return this.chargerStatus;
            })
            .catch(error => {
                this.chargerStatusError();
                this.chargerDidDisappear(error);
                return Observable.throw(error);
            })
            .retry()
            .share();
    }

    getChargerChannelRequests() {
        return this.channelStateObservable;
    }

    // Gets the status of the charger
    private getChargerURL(path) {
        let hostName = this.config.getHostName();
        return "http://" + hostName + path;
    }

    private chargerStatusError() {
        console.error("Unable to get charger status");
        this.events.publish(CHARGER_STATUS_ERROR);
    }

    private chargerDidDisappear(error) {
        if (this.isConnectedToCharger()) {
            console.error("Disconnected from the charger, ", error);
            this.events.publish(CHARGER_DISCONNECTED_EVENT);
        }
        this.chargerStatus = {};
    }

    private chargerDidAppear(statusDict) {
        this.numberOfChannels = statusDict['channel_count'];
        console.log(`Charger appeared, with ${this.numberOfChannels} channels`);

        // Clear existing observables
        // TODO: do we need to clean these up?
        this.channelStateObservable = [];

        // Creates a series of hot observables for channel data from the charger
        for (let i = 0; i < this.getNumberOfChannels(); i++) {
            console.debug(`Creating hot channel observable: ${i}`);
            this.channelStateObservable.push(Observable
                .timer(500, 1000)
                .filter(() => {
                    return this.isConnectedToCharger();
                })
                .flatMap((v) => {
                    return this.http.get(this.getChargerURL(`/channel/${i}`));
                })
                .map((response) => {
                    this.events.publish(CHARGER_CHANNEL_EVENT, i);
                    let jsonResponse = response.json();

                    // Maybe reduce the channels, as long as they are 0 volt.
                    let cellLimit = this.config.getCellLimit();
                    let channel = new Channel(i, jsonResponse, cellLimit);
                    this.channelSnapshots[i] = channel;
                    return channel;
                })
                .retry()
                .share()
            );
        }

        // Now need to sort them based on their actual channel number
        // But can't do that until we get the data (which is async)

        console.debug("Subscriptions are: ", this.channelStateObservable);
        this.events.publish(CHARGER_CONNECTED_EVENT);
    }

    lookupChargerMetadata(deviceId = null, propertyName = 'name', defaultValue = null) {
        // Not supplied? Look it up.
        if (deviceId == null) {
            if (this.chargerStatus) {
                deviceId = Number(this.chargerStatus['device_id']);
            }
        }
        if (deviceId) {
            let md = ChargerMetadata[deviceId];
            if (md) {
                if (md[propertyName]) {
                    return md[propertyName];
                }
            }
        }
        return defaultValue;
    }

    getMaxAmpsPerChannel() {
        return this.lookupChargerMetadata(null, 'maxAmps', 15);
    }

    getChargerName() {
        return this.lookupChargerMetadata(null, 'name', 'iCharger');
    }

    getChargerTag() {
        return this.lookupChargerMetadata(null, 'tag', '');
    }

    getMaxCells() {
        return this.lookupChargerMetadata(null, 'cells', 0);
    }

    // Mock data, representing an empty channel
    emptyData(channelNumber: number) {
        let cellLimit = this.getMaxCells();
        let cells = [];
        for (let i = 0; i > cellLimit; i++) {
            cells.push({
                'v': 0,
                'cell': i,
                'balance': 0,
                'ir': 0,
            });
        }
        let channelData = {
            curr_inp_volts: 0,
            curr_out_amps: 0,
            curr_out_capacity: 0,
            timestamp: 0,
            curr_int_temp: 0,
            cells: cells
        };
        return new Channel(channelNumber, channelData, this.config.getCellLimit());
    }

    savePreset(preset: Preset): Observable<any> {
        // An existing preset? in a memory slot?
        return Observable.create((observable) => {
            let addingNewPreset = preset.index < 0;
            let putURL = addingNewPreset ? this.getChargerURL("/addpreset") : this.getChargerURL("/preset/" + preset.index);
            let body = preset.json();
            console.log("Saving Preset: ", body);

            let headers = new Headers({ 'Content-Type': 'application/json' });
            let options = new RequestOptions({ headers: headers });

            this.http.put(putURL, body, options).subscribe((resp) => {
                // Expect a copy of the modified preset?
                // If we were adding, the preset is returned. If we're saving, it isn't.
                // At the moment, it just returns "ok"
                if (resp.ok) {
                    // Yay
                    if (addingNewPreset) {
                        // Return the newly saved preset, with its new memory slot (index)
                        let new_preset = new Preset(resp.json());
                        observable.next(new_preset);
                    } else {
                        // Just return the modified preset, that the user just saved
                        observable.next(preset);
                    }
                    observable.complete();
                } else {
                    observable.error(resp);
                }
            }, (error) => {
                console.log("Error saving preset: ", error);
                this.events.publish(CHARGER_COMMAND_FAILURE, error);
                observable.error(error);
            });

        });
    }
}

export {
    CHARGER_CONNECTED_EVENT,
    CHARGER_DISCONNECTED_EVENT,
    CHARGER_STATUS_ERROR,
    CHARGER_COMMAND_FAILURE,
    CHARGER_CHANNEL_EVENT,
}
