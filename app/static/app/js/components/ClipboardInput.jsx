import React from 'react';
import PropTypes from 'prop-types';
import Clipboard from 'clipboard';
import '../css/ClipboardInput.scss';
import { _ } from '../classes/gettext';

class ClipboardInput extends React.Component{
  constructor(props){
    super(props);

    this.state = {
      showCopied: false
    };
  }

  componentDidMount(){
    this.clipboard = new Clipboard(this.dom, {
        target: () => this.dom
      }).on('success', () => {
        this.setState({showCopied: true});
      });
  }

  componentWillUnmount(){
    this.clipboard.destroy();
  }

  render(){
    return (
      <div className="clipboardInput">
        <input 
          {...this.props}
          ref={(domNode) => { this.dom = domNode; }}
          title={this.props.value || ""}
          onBlur={() => { this.setState({showCopied: false}); }}
         />
        <div style={{position: 'relative', 'width': '100%'}}>
          <div className={"copied theme-background-success " + (this.state.showCopied ? "show" : "")}>{_("Copied to clipboard")}</div>
        </div>
    </div>);
  }       
}

export default ClipboardInput;