Name:           testrpm
Version:        0.1
Release:        1%{?dist}
Summary:        A simple test RPM package

License:        MIT
URL:            https://testrpmexample.com/testrpm
Source0:        https://testrpmexample.com/testrpm-0.1.tar.gz
Source1:        https://testrpmexample.com/testrpm-0.1.tar.gz.sig

BuildArch:      noarch

%description
This is a simple test RPM package for testing purposes.

%prep
%autosetup

%build
# no-op

%install
mkdir -p %{buildroot}%{_bindir}
touch %{buildroot}%{_bindir}/testrpm

%files
%{_bindir}/testrpm

%changelog
* Wed Oct 01 2024 Your Name <your.email@testrpmexample.com> - 0.1-1
- Initial package