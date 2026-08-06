import React from 'react';
import { shallow } from 'enzyme';
import ProjectList from '../ProjectList';
import $ from 'jquery';

describe('<ProjectList />', () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });

  it('renders without exploding', () => {
    const wrapper = shallow(<ProjectList history={{}} />);
    expect(wrapper.exists()).toBe(true);
  });

  it('uses the page size returned by the API', () => {
    const request = {
      fail: jest.fn().mockReturnThis(),
      always: jest.fn().mockReturnThis(),
      abort: jest.fn()
    };
    jest.spyOn($, 'getJSON').mockImplementation((source, done) => {
      done({
        count: 250,
        page_size: 100,
        results: [{id: 1}]
      });
      return request;
    });

    const wrapper = shallow(<ProjectList history={{}} source="/api/projects/?page=1" />);

    expect(wrapper.state('pagination')).toEqual({
      switchingPages: false,
      itemsPerPage: 100,
      totalItems: 250
    });
  });
});
