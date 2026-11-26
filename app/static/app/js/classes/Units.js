import { _ } from './gettext';

const types = {
    LENGTH: 1,
    AREA: 2,
    VOLUME: 3,
    TEMPERATURE: 4,
    PITCH: 5
};

const units = {
    acres: {
        factor: (1 / (0.3048 * 0.3048)) / 43560,
        abbr: 'ac',
        round: 5,
        label: _("Acres"),
        type: types.AREA
    },
    acres_us: {
      factor: Math.pow(3937 / 1200, 2) / 43560,
      abbr: 'ac (US)',
      round: 5,
      label: _("Acres"),
      type: types.AREA
    },
    feet: {
      factor: 1 / 0.3048,
      abbr: 'ft',
      round: 4,
      label: _("Feet"),
      type: types.LENGTH
    },
    feet_us:{
      factor: 3937 / 1200,
      abbr: 'ft (US)',
      round: 4,
      label: _("Feet"),
      type: types.LENGTH
    },
    inches:{
      factor: 100 / 2.54,
      abbr: 'in',
      round: 2,
      label: _("Inches"),
      type: types.LENGTH
    },
    hectares: {
      factor: 0.0001,
      abbr: 'ha',
      round: 4,
      label: _("Hectares"),
      type: types.AREA
    },
    meters: {
      factor: 1,
      abbr: 'm',
      round: 3,
      label: _("Meters"),
      type: types.LENGTH
    },
    kilometers: {
        factor: 0.001,
        abbr: 'km',
        round: 5,
        label: _("Kilometers"),
        type: types.LENGTH
    },
    centimeters: {
      factor: 100,
      abbr: 'cm',
      round: 2,
      label: _("Centimeters"),
      type: types.LENGTH
    },
    miles: {
        factor: (1 / 0.3048) / 5280,
        abbr: 'mi',
        round: 5,
        label: _("Miles"),
        type: types.LENGTH
    },
    miles_us: {
        factor: (3937 / 1200) / 5280,
        abbr: 'mi (US)',
        round: 5,
        label: _("Miles"),
        type: types.LENGTH
    },
    sqfeet: {
      factor: 1 / (0.3048 * 0.3048),
      abbr: 'ft²',
      round: 2,
      label: _("Square Feet"),
      type: types.AREA
    },
    sqfeet_us: {
        factor: Math.pow(3937 / 1200, 2),
        abbr: 'ft² (US)',
        round: 2,
        label: _("Square Feet"),
        type: types.AREA
    },
    sqmeters: {
      factor: 1,
      abbr: 'm²',
      round: 2,
      label: _("Square Meters"),
      type: types.AREA
    },
    sqkilometers: {
        factor: 0.000001,
        abbr: 'km²',
        round: 5,
        label: _("Square Kilometers"),
        type: types.AREA
    },
    sqmiles: {
      factor: Math.pow((1 / 0.3048) / 5280, 2),
      abbr: 'mi²',
      round: 5,
      label: _("Square Miles"),
      type: types.AREA
    },
    sqmiles_us: {
        factor: Math.pow((3937 / 1200) / 5280, 2),
        abbr: 'mi² (US)',
        round: 5,
        label: _("Square Miles"),
        type: types.AREA
    },
    cbmeters:{
        factor: 1,
        abbr: 'm³',
        round: 4,
        label: _("Cubic Meters"),
        type: types.VOLUME
    },
    cbyards:{
        factor: Math.pow(1/(0.3048*3), 3),
        abbr: 'yd³',
        round: 4,
        label: _("Cubic Yards"),
        type: types.VOLUME
    },
    cbyards_us:{
        factor: Math.pow(3937/3600, 3),
        abbr: 'yd³ (US)',
        round: 4,
        label: _("Cubic Yards"),
        type: types.VOLUME
    },
    celsius:{
        conversion:{
            forward: celsius => celsius,
            backward: celsius => celsius
        },
        abbr: '°C',
        round: 1,
        label: _("Celsius"),
        type: types.TEMPERATURE
    },
    fahrenheit:{
        conversion: {
            forward: celsius => (9.0 / 5.0) * celsius + 32.0,
            backward: fahrenheit => (fahrenheit - 32.0) * (5.0 / 9.0)
        },
        abbr: '°F',
        round: 1,
        label: _("Fahrenheit"),
        type: types.TEMPERATURE
    },
    degrees:{
        conversion:{
            forward: degrees => degrees,
            backward: degrees => degrees
        },
        abbr: '°',
        round: 1,
        label: _("Degrees"),
        type: types.PITCH
    },
    rise12:{
        conversion:{
            forward: degrees => Math.tan(degrees * Math.PI / 180) * 12,
            backward: rise => Math.atan(rise / 12) * 180 / Math.PI
        },
        abbr: '/12',
        round: 1,
        label: _("Rise Over 12"),
        type: types.PITCH
    }
};

class ValueUnit{
    constructor(value, unit){
        this.value = value;
        this.unit = unit;
    }

    toString(opts = {}){
        const mul = Math.pow(10, opts.precision !== undefined ? opts.precision : this.unit.round);
        const rounded = (Math.round(this.value * mul) / mul).toString();

        let withCommas = "";
        let parts = rounded.split(".");
        parts[0] = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, ",");
        withCommas = parts.join(".");

        return `${withCommas}${this.unit.type === types.PITCH ? "" : " "}${this.unit.abbr}`;
    }
}

class NanUnit{
    constructor(){
        this.value = NaN;
        this.unit = units.meters; // Don't matter
    }
    toString(){
        return "NaN";
    }
}

class UnitSystem{
    lengthUnit(meters, opts = {}){ throw new Error("Not implemented"); }
    areaUnit(sqmeters, opts = {}){ throw new Error("Not implemented"); }
    volumeUnit(cbmeters, opts = {}){ throw new Error("Not implemented"); }
    temperatureUnit(celsius, opts = {}){ throw new Error("Not implemented"); }
    pitchUnit(degrees, opts = {}){ throw new Error("Not implemented"); }
    
    getName(){ throw new Error("Not implemented"); }
    getKey(){ throw new Error("Not implemented"); }
    
    area(sqmeters, opts = {}){
        sqmeters = parseFloat(sqmeters);
        if (isNaN(sqmeters)) return new NanUnit();

        const unit = this.areaUnit(sqmeters, opts);
        const val = unit.factor * sqmeters;
        return new ValueUnit(val, unit);
    }

    elevation(meters){
        return this.length(meters, { fixedUnit: true });
    }

    length(meters, opts = {}){
        meters = parseFloat(meters);
        if (isNaN(meters)) return new NanUnit();

        const unit = this.lengthUnit(meters, opts);
        const val = unit.factor * meters;
        return new ValueUnit(val, unit);
    }

    volume(cbmeters, opts = {}){
        cbmeters = parseFloat(cbmeters);
        if (isNaN(cbmeters)) return new NanUnit();

        const unit = this.volumeUnit(cbmeters, opts);
        const val = unit.factor * cbmeters;
        return new ValueUnit(val, unit);
    }

    temperature(celsius, opts = {}){
        celsius = parseFloat(celsius);
        if (isNaN(celsius)) return new NanUnit();

        const unit = this.temperatureUnit(celsius, opts);
        const val = unit.conversion.forward(celsius);
        return new ValueUnit(val, unit);
    }

    pitch(degrees, opts = {}){
        degrees = parseFloat(degrees);
        if (isNaN(degrees)) return new NanUnit();

        const unit = this.pitchUnit(degrees, opts);
        const val = unit.conversion.forward(degrees);
        return new ValueUnit(val, unit);
    }
};

function toMetric(valueUnit, unit){
    let value = NaN;
    if (typeof valueUnit === "object" && unit === undefined){
        value = valueUnit.value;
        unit = valueUnit.unit;
    }else{
        value = parseFloat(valueUnit);
    }
    if (isNaN(value)) return new NanUnit();

    let val;
    if (unit.factor !== undefined){
        val = value / unit.factor;
    }else if (unit.conversion !== undefined){
        val = unit.conversion.backward(value);
    }else{
        throw new Error(`No unit factor or conversion: ${unit.type}`);
    }

    if (unit.type === types.LENGTH){
        return new ValueUnit(val, units.meters);
    }else if (unit.type === types.AREA){
        return new ValueUnit(val, units.sqmeters);
    }else if (unit.type === types.VOLUME){
        return new ValueUnit(val, units.cbmeters);
    }else if (unit.type === types.TEMPERATURE){
        return new ValueUnit(val, units.celsius);
    }else if (unit.type === types.PITCH){
        return new ValueUnit(val, units.degrees);
    }else{
        throw new Error(`Unrecognized unit type: ${unit.type}`);
    }
}

class MetricSystem extends UnitSystem{
    getName(){
        return _("Metric");
    }

    getKey(){
        return "metric";
    }

    lengthUnit(meters, opts = {}){
        if (opts.fixedUnit) return units.meters;
        if (opts.gsd) return units.centimeters;

        if (meters < 1) return units.centimeters;
        else if (meters >= 1000) return units.kilometers;
        else return units.meters;
    }

    areaUnit(sqmeters, opts = {}){
        if (opts.fixedUnit) return units.sqmeters;

        if (sqmeters >= 10000 && sqmeters < 1000000) return units.hectares;
        else if (sqmeters >= 1000000) return units.sqkilometers;
        return units.sqmeters;
    }

    volumeUnit(cbmeters, opts = {}){
        return units.cbmeters;
    }

    temperatureUnit(celsius, opts = {}){
        return units.celsius;
    }

    pitchUnit(degrees, opts = {}){
        return units.degrees;
    }
}

class ImperialSystem extends UnitSystem{
    getName(){
        return _("Imperial");
    }

    getKey(){
        return "imperial";
    }

    feet(){
        return units.feet;
    }

    sqfeet(){
        return units.sqfeet;
    }

    inches(){
        return units.inches;
    }

    miles(){
        return units.miles;
    }

    sqmiles(){
        return units.sqmiles;
    }

    acres(){
        return units.acres;
    }

    cbyards(){
        return units.cbyards;
    }
    
    lengthUnit(meters, opts = {}){
        if (opts.fixedUnit) return this.feet();
        if (opts.gsd) return this.inches();

        const feet = this.feet().factor * meters;
        if (feet >= 5280) return this.miles();
        else return this.feet();
    }

    areaUnit(sqmeters, opts = {}){
        if (opts.fixedUnit) return this.sqfeet();

        const sqfeet = this.sqfeet().factor * sqmeters;
        if (sqfeet >= 43560 && sqfeet < 27878400) return this.acres();
        else if (sqfeet >= 27878400) return this.sqmiles();
        else return this.sqfeet();
    }

    volumeUnit(cbmeters, opts = {}){
        return this.cbyards();
    }

    temperatureUnit(celsius, opts = {}){
        return units.fahrenheit;
    }

    pitchUnit(degrees, opts = {}){
        return units.rise12;
    }
}

class ImperialUSSystem extends ImperialSystem{
    getName(){
        return _("Imperial (US)");
    }

    getKey(){
        return "imperialUS";
    }

    feet(){
        return units.feet_us;
    }

    sqfeet(){
        return units.sqfeet_us;
    }

    inches(){
        return units.inches;
    }

    miles(){
        return units.miles_us;
    }

    sqmiles(){
        return units.sqmiles_us;
    }

    acres(){
        return units.acres_us;
    }

    cbyards(){
        return units.cbyards_us;
    }
}

const systems = {
    metric: new MetricSystem(),
    imperial: new ImperialSystem(),
    imperialUS: new ImperialUSSystem()
}

// Expose to allow every part of the app to access this information
function getUnitSystem(){
    return localStorage.getItem("unit_system") || "metric";
}
function setUnitSystem(system){
    let prevSystem = getUnitSystem();
    localStorage.setItem("unit_system", system);
    if (prevSystem !== system){
        document.dispatchEvent(new CustomEvent("onUnitSystemChanged", { detail: system }));
    }
}

function onUnitSystemChanged(callback){
    document.addEventListener("onUnitSystemChanged", callback);
}

function offUnitSystemChanged(callback){
    document.removeEventListener("onUnitSystemChanged", callback);
}

function unitSystem(){
    return systems[getUnitSystem()];
}

export {
    systems,
    types,
    toMetric,
    unitSystem,
    getUnitSystem,
    setUnitSystem,
    onUnitSystemChanged,
    offUnitSystemChanged
};

