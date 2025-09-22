Name:           testrpm
Version:        0.1
Release:        1%{?dist}
Summary:        A simple test RPM package for testing repo suggestions

License:        MIT
URL:            https://example.com/testrpm
Source0:        testrpm-0.1.tar

BuildArch:      noarch

%description
This is a simple test RPM package for testing repo suggestions.
The package is hosted at https://github.com/testrpm/testrpm
with a mirror at https://example.com/git/testrpm.git

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
* Wed Oct 01 2024 Your Name <your.email@example.com> - 0.1-1
- Initial package
