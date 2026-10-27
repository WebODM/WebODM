import React from 'react';
import '../css/ProcessingNodeOption.scss';
import PropTypes from 'prop-types';
import $ from 'jquery';
import { _ } from '../classes/gettext';
import TaskOptionsPluginItems from './TaskOptionsPluginItems';

const warnings = {
    'ignore-gsd': _("You might run out of memory if you use this option.")
};

class ProcessingNodeOption extends React.Component {
  static defaultProps = {};

  static propTypes = {
    name: PropTypes.string.isRequired,
    defaultValue: PropTypes.oneOfType([
      PropTypes.string,
      PropTypes.number,
      PropTypes.bool
    ]).isRequired,
    value: PropTypes.oneOfType([
      PropTypes.string,
      PropTypes.number,
      PropTypes.bool
    ]),
    type: PropTypes.string,
    domain: PropTypes.oneOfType([
      PropTypes.string,
      PropTypes.array
    ]),
    help: PropTypes.string,

    // Given only when a plugin uses addTaskOptionControl
    pluginContext: PropTypes.object,
    taskOptions: PropTypes.object
  };

  constructor(props){
    super();

    this.state = {
      value: props.value !== undefined ? props.value : ""
    };

    this.resetToDefault = this.resetToDefault.bind(this);
    this.handleInputChange = this.handleInputChange.bind(this);
    this.handleCheckboxChange = this.handleCheckboxChange.bind(this);
    this.handleSelectChange = this.handleSelectChange.bind(this);
    this.isEnumType = this.isEnumType.bind(this);
    this.supportsFileAPI = this.supportsFileAPI.bind(this);
    this.loadFile = this.loadFile.bind(this);
    this.handleFileSelect = this.handleFileSelect.bind(this);
  }

  getValue(){
    return this.state.value !== "" ? this.state.value : undefined;
  }

  // Sets the value as if the user had typed it (undefined, null or false: the default)
  setValue = value => {
    if (value === undefined || value === null || value === false ||
        (this.isEnumType() && value === this.props.defaultValue)) value = "";
    this.setState({value});
  }

  setTooltips(domNode){
    if (domNode !== null) $(domNode).find('[data-toggle="tooltip"]').tooltip();
  }

  resetToDefault(e){
    this.setState({value: ""});
    e.preventDefault();
  }

  handleInputChange(e){
    this.setState({value: e.target.value});
  }

  handleSelectChange(e){
    this.setState({value: e.target.value !== this.props.defaultValue ? e.target.value : ""});
  }

  handleCheckboxChange(e){
    this.setState({value: this.state.value === "" ? true : ""});
  }

  isEnumType(){
    return this.props.type === 'enum' && Array.isArray(this.props.domain);
  }

  supportsFileAPI(){
    return window.File && window.FileReader && window.FileList && window.Blob;
  }

  loadFile(){
    if (this.fileControl){
      let evt = document.createEvent("MouseEvents");
      evt.initEvent("click", true, false);
      this.fileControl.dispatchEvent(evt);
    }
  }

  handleFileSelect(evt){
    const files = evt.target.files; // FileList object
    if (files.length > 0){
        let file = files[0];

        const reader = new FileReader();
        reader.onload =  (e) => {
            try{
                let value = JSON.stringify(JSON.parse(e.target.result));
                this.setState({value});
            }catch(e){
                console.warn(`Cannot parse JSON: ${e.target.result}: ${e}`);
            }
            this.fileControl.value = '';
        };
        reader.readAsText(file);
    }
  }

  getPluginOption(){
    const { name, type, domain, help, defaultValue } = this.props;
    return { name, type, domain, help, defaultValue };
  }

  handleHelp = e => {
    e.preventDefault();
    if (window.__taskOptionsDocsLink){
      window.open(window.__taskOptionsDocsLink + "#" + encodeURIComponent(this.props.name), "task-options")
    }
  }

  render() {
    let inputControl = "";
    let warningMsg = "";

    if (this.props.type !== 'bool'){
      if (this.isEnumType()){
        // Enum
        let selectValue = this.state.value !== "" ? 
                          this.state.value : 
                          this.props.defaultValue; 
        inputControl = (
            <select
              className="form-control"
              value={selectValue}
              onChange={this.handleSelectChange}>
                {this.props.domain.map(val => 
                  <option value={val} key={val}>{val}</option>
                )}
            </select>
          );
      }else{
        // String, numbers, etc.
        inputControl = (
            <input type="text" 
              className="form-control"
              placeholder={this.props.defaultValue}
              value={this.state.value}
              onChange={this.handleInputChange} />
          );
      }
    }else{
      // Boolean
      inputControl = (
          <div className="checkbox">
            <label>
              <input type="checkbox"
                    checked={this.state.value !== ""}
                    onChange={this.handleCheckboxChange} /> {_("Enable")}
            </label>
          </div>
        );
    }

    let loadFileControl = "";
    if (this.supportsFileAPI() && this.props.domain === 'json'){
        loadFileControl = ([
            <button key="btn" type="file" className="btn glyphicon glyphicon-import btn-primary" data-toggle="tooltip" data-placement="left" title={_("Click to import a JSON file")} onClick={() => this.loadFile()}></button>,
            <input key="file-ctrl" className="file-control" type="file" 
                accept="text/plain,application/json,application/geo+json,.geojson"
                onChange={this.handleFileSelect}
                ref={(domNode) => { this.fileControl = domNode}} />
        ]);
    }

    if (warnings[this.props.name] !== undefined && this.state.value !== ""){
        warningMsg = (<div class="alert alert-warning">
                <i class="fa fa-exclamation-triangle"></i> {warnings[this.props.name]}
            </div>);
    }

    return (
      <div className="processing-node-option form-inline form-group form-horizontal" ref={this.setTooltips}>
        <label>{this.props.name} {(!this.isEnumType() && this.props.domain ? `(${this.props.domain})` : "")} <i data-toggle="tooltip" data-placement="bottom" title={this.props.help} onClick={this.handleHelp} className="fa fa-info-circle info-button help-button"></i></label><br/>
        {inputControl}
        {loadFileControl}
        
        {this.state.value !== "" ? 
        <button type="submit" className="btn glyphicon glyphicon glyphicon-repeat btn-default" data-toggle="tooltip" data-placement="top" title={_("Reset to default")} onClick={this.resetToDefault}></button> :
        ""}

        {this.props.taskOptions ?
        <TaskOptionsPluginItems
          hook="addTaskOptionControl"
          className="option-plugin-controls"
          inline={true}
          args={{option: this.getPluginOption(), context: this.props.pluginContext}}
          itemProps={{
            option: this.getPluginOption(),
            value: this.getValue(),
            setValue: this.setValue,
            context: this.props.pluginContext,
            taskOptions: this.props.taskOptions
          }} /> : ""}

        {warningMsg}
      </div>
    );
  }
}

export default ProcessingNodeOption;
