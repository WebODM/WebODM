import React from 'react';
import { shallow } from 'enzyme';
import EditTaskForm from '../EditTaskForm';

describe('<EditTaskForm />', () => {
  it('renders without exploding', () => {
    const wrapper = shallow(<EditTaskForm />);
    expect(wrapper.exists()).toBe(true);
  })
});