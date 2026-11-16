import React from 'react';
import PropTypes from 'prop-types';
import '../css/PdfPopup.scss';
import { _ } from '../classes/gettext';

class PdfPopup extends React.Component {
    static propTypes = {
        url: PropTypes.string.isRequired,
        title: PropTypes.string,
        onClose: PropTypes.func.isRequired
    };

    constructor(props){
        super(props);

        this.state = {
            
        }
    }

    componentDidMount(){
        document.body.style.overflow = 'hidden';
    }

    componentWillUnmount(){
        document.body.style.overflow = 'auto';
    }


    render(){
        return (
            <div className="pdf-popup" onClick={this.props.onClose}>
                <div className="pdf-popup-header">
                    {this.props.title ? <div className="pdf-popup-title">{this.props.title}</div> : ""}
                    <button 
                        className="btn-close btn btn-secondary btn-sm" 
                        onClick={this.props.onClose}
                        aria-label={_("Close")}
                    >
                        <i className="fa fa-times"></i>
                    </button>
                </div>
                <div className="pdf-popup-content">
                    <iframe
                        src={this.props.url}
                    />
                </div>
            </div>
        );
    }
}

export default PdfPopup;
